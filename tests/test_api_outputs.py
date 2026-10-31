import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from officeworker import io, server


class ApiOutputTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        root_patch = patch.object(server, "ROOT", self.root)
        root_patch.start()
        self.addCleanup(root_patch.stop)
        auth_patch = patch.dict(os.environ, {"OW_API_TOKEN": "output-test"})
        auth_patch.start()
        self.addCleanup(auth_patch.stop)
        self.client = TestClient(server.app)
        self.addCleanup(self.client.close)
        self.headers = {"x-token": "output-test"}

    def test_default_merge_outputs_keep_each_request_result(self):
        results = []
        for value in (100, 200):
            response = self.client.post("/merge", headers=self.headers,
                                        files={"file": ("sales.csv", f"amount\n{value}\n".encode(), "text/csv")})
            self.assertEqual(response.status_code, 200)
            results.append(Path(response.json()["file"]))
        self.assertNotEqual(*results)
        self.assertEqual([io.read_any(path)["amount"].tolist() for path in results], [[100], [200]])

    def test_explicit_output_preserves_existing_file(self):
        destination = self.root / "out" / "client.xlsx"
        destination.parent.mkdir()
        original = b"existing client result"
        destination.write_bytes(original)
        response = self.client.post("/merge", headers=self.headers, params={"out": "out/client.xlsx"},
                                    files={"file": ("sales.csv", b"amount\n200\n", "text/csv")})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(destination.read_bytes(), original)
        result = Path(response.json()["file"])
        self.assertEqual(result.parent, destination.parent)
        self.assertEqual(io.read_any(result)["amount"].tolist(), [200])

    def test_invoice_outputs_are_separate_for_each_request(self):
        results = []
        with patch.object(server.pdf, "invoice", side_effect=[{"total": 100}, {"total": 200}]):
            for _ in range(2):
                response = self.client.post("/invoice", headers=self.headers,
                                            files={"file": ("invoice.pdf", b"fixture", "application/pdf")})
                self.assertEqual(response.status_code, 200)
                results.append(Path(response.json()["file"]))
        self.assertNotEqual(*results)
        self.assertEqual([io.read_any(path)["total"].tolist() for path in results], [[100], [200]])


if __name__ == "__main__":
    unittest.main()
