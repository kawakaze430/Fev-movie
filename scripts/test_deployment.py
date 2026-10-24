"""Standalone deployment tests; AWS and HTTP are mocked, never provisioned."""
from argparse import Namespace
import contextlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import zipfile

import deploy_amplify as deploy


def catalog(kind='public'):
    return {'schemaVersion': 1, 'generatedAt': '2026-10-23T00:00:00Z', 'kind': kind, 'movies': [{'id': 'sample', 'title': 'Synthetic test record', 'year': None, 'genres': ['Drama'], 'synopsis': 'Test fixture only.', 'poster': None, 'links': [], 'sources': [{'channelId': 'test', 'channelName': 'Test fixture', 'messageId': '1'}], 'rights': {'distribution': 'cleared', 'poster': 'none', 'evidence': 'Synthetic test fixture.'}}]}


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.zip_path = self.directory / 'site.zip'
        self.headers = self.directory / 'customHttp.yml'
        self.headers.write_text("customHeaders:\nContent-Security-Policy: default-src 'self'\nX-Content-Type-Options: nosniff\nStrict-Transport-Security: max-age=31536000")

    def tearDown(self):
        self.temporary.cleanup()

    def write_zip(self, document=None, extra=None):
        with zipfile.ZipFile(self.zip_path, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('index.html', '<html><div id="root"></div></html>')
            archive.writestr('data/movies.json', json.dumps(document or catalog()))
            for name, data in (extra or {}).items():
                archive.writestr(name, data)

    def test_valid_public_zip_and_hash(self):
        self.write_zip()
        payload, files, digest, count = deploy.preflight(self.zip_path)
        self.assertEqual(count, 1)
        self.assertEqual(set(files), {'index.html', 'data/movies.json'})
        self.assertTrue(payload)
        self.assertEqual(len(digest), 64)
        with self.assertRaisesRegex(deploy.DeploymentError, 'SHA256'):
            deploy.preflight(self.zip_path, '0' * 64)

    def test_private_files_paths_and_symlinks_rejected(self):
        for name in ['../private.json', 'messages.html', 'data/inventory.json', '.env', 'dist/index.html']:
            with self.subTest(name=name):
                self.write_zip(extra={name: 'private'})
                with self.assertRaises(deploy.DeploymentError):
                    deploy.preflight(self.zip_path)
        self.write_zip()
        with zipfile.ZipFile(self.zip_path, 'a') as archive:
            entry = zipfile.ZipInfo('assets/link.js')
            entry.create_system = 3
            entry.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(entry, '/private/secret')
        with self.assertRaisesRegex(deploy.DeploymentError, 'Linked'):
            deploy.preflight(self.zip_path)

    def test_demo_requires_explicit_opt_in(self):
        self.write_zip(catalog('demo'))
        with self.assertRaisesRegex(deploy.DeploymentError, 'fictional demo'):
            deploy.preflight(self.zip_path)
        self.assertEqual(deploy.preflight(self.zip_path, allow_demo=True)[3], 1)

    def test_catalog_rights_and_private_fields_rejected(self):
        document = catalog()
        document['movies'][0]['rights']['distribution'] = 'pending'
        self.write_zip(document)
        with self.assertRaisesRegex(deploy.DeploymentError, 'clearance'):
            deploy.preflight(self.zip_path)
        document = catalog()
        document['movies'][0]['rawMessage'] = 'Do not publish'
        self.write_zip(document)
        with self.assertRaisesRegex(deploy.DeploymentError, 'unexpected'):
            deploy.preflight(self.zip_path)

    def test_private_url_and_orphan_art_rejected(self):
        document = catalog()
        document['movies'][0]['links'] = [{'label': 'bad', 'quality': None, 'url': 'http://127.1/private', 'size': None}]
        self.write_zip(document)
        with self.assertRaisesRegex(deploy.DeploymentError, 'Unsafe public external'):
            deploy.preflight(self.zip_path)
        self.write_zip(extra={'posters/orphan.svg': '<svg/>'})
        with self.assertRaisesRegex(deploy.DeploymentError, 'Unreferenced'):
            deploy.preflight(self.zip_path)

    def test_dry_run_does_not_require_cli_credentials_or_network(self):
        self.write_zip()
        with patch.object(deploy, 'aws') as aws, patch.object(deploy, 'build_opener') as opener, contextlib.redirect_stdout(io.StringIO()):
            result = deploy.main(['--site-zip', str(self.zip_path), '--headers', str(self.headers), '--dry-run'])
        self.assertEqual(result, 0)
        aws.assert_not_called()
        opener.assert_not_called()

    def test_aws_cli_preserves_profile_and_redacts_error_details(self):
        completed = subprocess.CompletedProcess([], 0, '{"Account":"123456789012"}', '')
        with patch.dict(os.environ, {'AWS_PROFILE': 'existing-profile'}), patch.object(deploy.subprocess, 'run', return_value=completed) as run:
            self.assertEqual(deploy.aws('sts', 'get-caller-identity', 'ap-south-1')['Account'], '123456789012')
            self.assertEqual(run.call_args.kwargs['env']['AWS_PROFILE'], 'existing-profile')
            self.assertEqual(run.call_args.kwargs['env']['AWS_CLI_AUTO_PROMPT'], 'off')
        failed = subprocess.CompletedProcess([], 1, '', 'An error occurred (AccessDeniedException): https://bucket.s3.amazonaws.com/?SECRET_UPLOAD_TOKEN')
        with patch.object(deploy.subprocess, 'run', return_value=failed), self.assertRaises(deploy.AWSFailure) as error:
            deploy.aws('amplify', 'create-app', 'ap-south-1')
        self.assertIn('AccessDeniedException', str(error.exception))
        self.assertNotIn('SECRET_UPLOAD_TOKEN', str(error.exception))

    def test_upload_failure_never_logs_signed_url(self):
        url = 'https://bucket.s3.ap-south-1.amazonaws.com/site.zip?X-Amz-Signature=SECRET_UPLOAD_TOKEN'
        opener = MagicMock()
        opener.open.side_effect = RuntimeError(url)
        output = io.StringIO()
        with patch.object(deploy, 'build_opener', return_value=opener), contextlib.redirect_stdout(output), self.assertRaises(deploy.DeploymentError) as error:
            deploy.upload_archive(url, b'zip')
        self.assertNotIn('SECRET_UPLOAD_TOKEN', str(error.exception) + output.getvalue())
        self.assertEqual(opener.open.call_args.args[0].method, 'PUT')
        with patch.object(deploy, 'build_opener') as build, self.assertRaises(deploy.DeploymentError):
            deploy.upload_archive('http://bucket.s3.amazonaws.com/site.zip?secret', b'zip')
        build.assert_not_called()
        with patch.object(deploy, 'build_opener') as build, self.assertRaises(deploy.DeploymentError):
            deploy.upload_archive('https://bucket.s3.attacker.amazonaws.com/site.zip?secret', b'zip')
        build.assert_not_called()

    def test_upload_failure_prevents_start_deployment(self):
        args = Namespace(region='ap-south-1', headers=self.headers, app_id=None, name='test', branch='main', timeout=60)
        calls = []
        def fake_aws(service, operation, region, *arguments):
            calls.append(operation)
            if operation == 'get-caller-identity':
                return {'Account': '123456789012'}
            if operation == 'create-app':
                return {'app': {'appId': 'd123test', 'defaultDomain': 'd123test.amplifyapp.com'}}
            if operation == 'get-branch':
                raise deploy.AWSFailure(service, operation, 'NotFoundException')
            if operation == 'create-deployment':
                return {'jobId': '1', 'zipUploadUrl': 'https://bucket.s3.amazonaws.com/site.zip?secret'}
            return {}
        with patch.object(deploy, 'aws', side_effect=fake_aws), patch.object(deploy, 'upload_archive', side_effect=deploy.DeploymentError('Upload failed')), contextlib.redirect_stdout(io.StringIO()), self.assertRaises(deploy.DeploymentError):
            deploy.deploy(args, b'zip', {})
        self.assertNotIn('start-deployment', calls)

    def test_failed_job_and_timeout_are_not_success(self):
        with patch.object(deploy, 'aws', return_value={'job': {'summary': {'status': 'FAILED'}}}), contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(deploy.DeploymentError, 'FAILED'):
            deploy.poll_job('d123test', 'main', '1', 'ap-south-1', 60)
        with patch.object(deploy, 'aws', return_value={'job': {'summary': {'status': 'RUNNING'}}}), patch.object(deploy.time, 'monotonic', side_effect=[0, 0, 0.5, 2]), patch.object(deploy.time, 'sleep') as sleep, contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(deploy.DeploymentError, 'timeout'):
            deploy.poll_job('d123test', 'main', '1', 'ap-south-1', 1)
        sleep.assert_called_once_with(0.5)

    def test_successful_deployment_uses_headers_and_verifies_public_bytes(self):
        args = Namespace(region='ap-south-1', headers=self.headers, app_id=None, name='test', branch='main', timeout=60)
        calls = []
        def fake_aws(service, operation, region, *arguments):
            calls.append((operation, arguments))
            if operation == 'get-caller-identity':
                return {'Account': '123456789012'}
            if operation == 'create-app':
                return {'app': {'appId': 'd123test', 'defaultDomain': 'd123test.amplifyapp.com'}}
            if operation == 'create-deployment':
                return {'jobId': '1', 'zipUploadUrl': 'https://bucket.s3.amazonaws.com/site.zip?secret'}
            return {}
        files = {'index.html': b'expected'}
        with patch.object(deploy, 'aws', side_effect=fake_aws), patch.object(deploy, 'upload_archive') as upload, patch.object(deploy, 'poll_job') as poll, patch.object(deploy, 'verify_site') as verify, contextlib.redirect_stdout(io.StringIO()):
            origin = deploy.deploy(args, b'zip', files)
        self.assertEqual(origin, 'https://main.d123test.amplifyapp.com')
        upload.assert_called_once()
        poll.assert_called_once()
        verify.assert_called_once_with(origin, files)
        self.assertIn('start-deployment', [operation for operation, _ in calls])
        create_arguments = next(arguments for operation, arguments in calls if operation == 'create-app')
        self.assertIn('--custom-headers', create_arguments)
        self.assertIn('file://' + str(self.headers), create_arguments)

    def test_existing_app_is_reused_without_creation_or_deletion(self):
        args = Namespace(region='ap-south-1', headers=self.headers, app_id='d123test', name='test', branch='main', timeout=60)
        calls = []
        def fake_aws(service, operation, region, *arguments):
            calls.append(operation)
            if operation == 'get-caller-identity':
                return {'Account': '123456789012'}
            if operation == 'get-app':
                return {'app': {'appId': 'd123test', 'platform': 'WEB', 'defaultDomain': 'd123test.amplifyapp.com'}}
            if operation == 'create-deployment':
                return {'jobId': '1', 'zipUploadUrl': 'https://bucket.s3.amazonaws.com/site.zip?secret'}
            return {}
        with patch.object(deploy, 'aws', side_effect=fake_aws), patch.object(deploy, 'upload_archive'), patch.object(deploy, 'poll_job'), patch.object(deploy, 'verify_site'), contextlib.redirect_stdout(io.StringIO()):
            deploy.deploy(args, b'zip', {})
        self.assertIn('update-app', calls)
        self.assertNotIn('create-app', calls)
        self.assertFalse(any('delete' in operation for operation in calls))

    def test_http_redirects_rejected_and_deployed_bytes_compared(self):
        with self.assertRaises(deploy.DeploymentError):
            deploy.NoRedirect().redirect_request(None, None, 302, 'redirect', {}, 'http://example.org')
        response = MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.read.return_value = b'changed'
        opener = MagicMock()
        opener.open.return_value = response
        with patch.object(deploy, 'build_opener', return_value=opener), self.assertRaisesRegex(deploy.DeploymentError, 'differs'):
            deploy.verify_site('https://main.d123test.amplifyapp.com', {'index.html': b'expected'})

    def test_verification_checks_visitor_root_and_security_headers(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.read.return_value = b'expected'
        response.headers = {'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'strict-origin-when-cross-origin', 'Strict-Transport-Security': 'max-age=31536000', 'Content-Security-Policy': "default-src 'self'; script-src 'self'; object-src 'none'; frame-ancestors 'none'"}
        opener = MagicMock()
        opener.open.return_value = response
        with patch.object(deploy, 'build_opener', return_value=opener):
            deploy.verify_site('https://main.d123test.amplifyapp.com', {'index.html': b'expected'})
        urls = [call.args[0].full_url for call in opener.open.call_args_list]
        self.assertEqual(urls, ['https://main.d123test.amplifyapp.com/', 'https://main.d123test.amplifyapp.com/index.html'])
        response.headers = {}
        with patch.object(deploy, 'build_opener', return_value=opener), self.assertRaisesRegex(deploy.DeploymentError, 'X-Content-Type-Options'):
            deploy.verify_site('https://main.d123test.amplifyapp.com', {'index.html': b'expected'})


if __name__ == '__main__':
    unittest.main()
