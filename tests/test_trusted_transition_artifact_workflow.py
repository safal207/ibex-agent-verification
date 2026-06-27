from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / ".github/workflows/proofqa-transition-source.yml").read_text(encoding="utf-8")
TRUSTED = (ROOT / ".github/workflows/trusted-transition-artifact.yml").read_text(encoding="utf-8")


class TrustedTransitionArtifactWorkflowTests(unittest.TestCase):
    def test_source_precedes_upload(self):
        build = SOURCE.index("python scripts/trusted_transition_reference_source.py")
        validate = SOURCE.index("python scripts/production_transition_source.py")
        upload = SOURCE.index("name: Upload exact reference source")
        self.assertLess(build, validate)
        self.assertLess(validate, upload)

    def test_ingestion_precedes_manifest(self):
        extract = TRUSTED.index("python scripts/trusted_transition_artifact.py extract")
        validate = TRUSTED.index("python scripts/production_transition_source.py")
        manifest = TRUSTED.index("python scripts/proofqa_transition_manifest_builder.py")
        self.assertLess(extract, validate)
        self.assertLess(validate, manifest)

    def test_workflow_names_are_exact(self):
        self.assertIn("ProofQA Release Gate Action", SOURCE)
        self.assertIn("ProofQA Transition Source Artifact", TRUSTED)


if __name__ == "__main__":
    unittest.main()
