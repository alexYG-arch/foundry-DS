"""Protocol delivery uses actual task context and does not change authority."""

from copy import deepcopy
import json
import unittest

from harness_foundry_factory.build_check_protocol import verification_interfaces
from harness_foundry_factory.build_runtime import classify_verification_result
import test_build_runtime as support
import test_build_resources as resources


class CheckProtocolTests(unittest.TestCase):
    def fixture(self, mode='pass'):
        owner=resources.BuildResourceIntegrationTests()
        f=owner.fixture(mode)
        self.addCleanup(owner.doCleanups)
        return f

    def test_actual_invocation_has_per_case_protocol_and_unchanged_authority(self):
        f=self.fixture()
        f.plan['workpacks'][0]['verification'][1].pop('resource_profile_ref')
        f.prepare()
        controller=f.controller();_,prepared,_=controller._current(f.prepared_id)
        events=deepcopy(f.events())
        inv=controller._invocation(prepared,f.plan['workpacks'][0],f.plan['workpacks'][0]['local_argv'])
        context=json.loads(inv['prompt'].split('\n',1)[1])['task']
        interfaces=context['verification_interfaces']
        self.assertEqual([i['case_id'] for i in interfaces],['READ-ROWS','REJECT-MALFORMED'])
        self.assertEqual(interfaces[0]['required_checks'],['temp','sqlite'])
        self.assertEqual(interfaces[0]['summary_environment'],'FOUNDRY_REPORT_DIR/summary.json')
        self.assertEqual(interfaces[1]['result_protocol'],'EXISTING_NON_RESOURCE_INTERFACE')
        self.assertEqual(inv['scope'],prepared['scope'])
        self.assertEqual(inv['write_roots'],[str(f.workspace/'src')])
        self.assertEqual(f.events(),events)
        self.assertEqual(f.runner.invocations,[])

    def test_projection_excludes_oracle_credential_and_unrelated_profile(self):
        f=self.fixture()
        scope=deepcopy(f.scope)
        p=scope['verification_resources']['profiles']['local']
        p['credentials']={'TOKEN':{'ref':'PRIVATE_CREDENTIAL_REF','purpose':'private'}}
        scope['verification_resources']['checker_files']=['PRIVATE_EXPECTED.json']
        scope['verification_resources']['profiles']['UNUSED']={**p,'required_checks':['UNRELATED']}
        projected=json.dumps(verification_interfaces(f.plan['workpacks'][0],scope))
        for private in ('PRIVATE_CREDENTIAL_REF','PRIVATE_EXPECTED','UNRELATED','UNUSED',str(f.verifier),str(f.root)):
            self.assertNotIn(private,projected)

    def test_local_and_remote_existing_additional_obligations_are_delivered(self):
        for mode,key in [('local-service','services_stopped'),('remote-service','external_effects')]:
            with self.subTest(mode=mode):
                f=self.fixture(mode)
                row=verification_interfaces(f.plan['workpacks'][0],f.scope)[0]
                self.assertIn(key,row['additional_report_fields'])

    def test_legacy_success_does_not_acquire_json_requirement(self):
        result={'status':'PASS','exit_code':0,'stdout':'ordinary existing checker output'}
        self.assertEqual(classify_verification_result(result),result)
        f=support.BuildRuntimeTests();f.setUp();self.addCleanup(f.doCleanups)
        rows=verification_interfaces(f.plan['workpacks'][0],f.scope)
        self.assertTrue(all(r['result_protocol']=='EXISTING_NON_RESOURCE_INTERFACE' for r in rows))

    def test_public_feedback_projects_only_the_public_reason(self):
        from harness_foundry_factory.build_check_protocol import public_feedback
        verdict={'status':'CHECKS_FAILED','failure_kind':'ASSERTION','public_reason':'count must be reported',
                 'private_detail':{'expected_rows':3,'fixture':'PRIVATE_FIXTURE'},'repair_artifact_ids':['UPSTREAM']}
        result={'status':'VALIDATION_FAILED','exit_code':1,'stdout':json.dumps(verdict),'stderr':'PRIVATE traceback',
                'failure_domain':'BUSINESS_ASSERTION','automatic_retry_allowed':True,'repair_artifact_ids':['UPSTREAM']}
        projected=public_feedback(result)
        self.assertEqual(projected['feedback_projection'],'PUBLIC_REASON_ONLY')
        self.assertEqual(projected['failure_domain'],'BUSINESS_ASSERTION')
        self.assertIsNone(projected['stderr'])
        text=json.dumps(projected)
        self.assertIn('count must be reported',text)
        for private in ('PRIVATE_FIXTURE','expected_rows','PRIVATE traceback','private_detail'):
            self.assertNotIn(private,text)
        # Checkers that do not separate the two keep the existing raw feedback (no projection).
        self.assertIsNone(public_feedback({'status':'VALIDATION_FAILED','stdout':'plain text failure'}))
        self.assertIsNone(public_feedback({'status':'VALIDATION_FAILED','stdout':json.dumps({'status':'CHECKS_FAILED','reason':'x'})}))
        self.assertIsNone(public_feedback({**result,'stdout_truncated':True}))

    def test_directory_manifest_binds_the_checker_root_but_not_its_caches(self):
        import tempfile
        from pathlib import Path
        from harness_foundry_factory.build_artifacts import directory_manifest
        from harness_foundry_factory.build_types import RequestValidationError
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/'check.py').write_text('print(1)\n')
            (root/'fixtures').mkdir();(root/'fixtures'/'expected.json').write_text('{}')
            (root/'__pycache__').mkdir();(root/'__pycache__'/'check.cpython-312.pyc').write_bytes(b'\x00')
            (root/'.DS_Store').write_bytes(b'junk')
            manifest=directory_manifest(root)
            self.assertEqual(set(manifest),{'check.py','fixtures/expected.json'})
            self.assertEqual(manifest['check.py']['size'],len('print(1)\n'))
            (root/'fixtures'/'expected.json').write_text('{"changed": true}')
            self.assertNotEqual(directory_manifest(root),manifest)
            for index in range(3):(root/f'extra{index}.txt').write_text('x')
            with self.assertRaisesRegex(RequestValidationError,'more than 4 files'):
                directory_manifest(root,max_files=4)


if __name__=='__main__':unittest.main()
