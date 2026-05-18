"""Unit tests for ``shared.calibration.calibration_sink``.

Verifies coercion tables, role/output_type validation, and end-to-end
prediction+outcome record routing with the ``outcome_corpus`` functions
mocked. No real Postgres.
"""
from __future__ import annotations

import asyncio
import unittest
from unittest import mock

from shared.calibration import calibration_sink as sink


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


class CoercionTests(unittest.TestCase):
    def test_severity_strings(self) -> None:
        self.assertEqual(sink._coerce_predicted("severity", "critical"), 1.0)
        self.assertEqual(sink._coerce_predicted("severity", "info"), 0.05)
        self.assertEqual(sink._coerce_predicted("severity", "MEDIUM"), 0.5)

    def test_risk_band_strings(self) -> None:
        self.assertEqual(sink._coerce_predicted("risk_band", "high_precision"), 0.9)
        self.assertEqual(sink._coerce_predicted("risk_band", "untrusted"), 0.1)

    def test_numeric_strings_clipped(self) -> None:
        self.assertEqual(sink._coerce_predicted("confidence", "1.5"), 1.0)
        self.assertEqual(sink._coerce_predicted("confidence", "-0.2"), 0.0)
        self.assertEqual(sink._coerce_predicted("confidence", "0.42"), 0.42)

    def test_booleans(self) -> None:
        self.assertEqual(sink._coerce_predicted("confidence", True), 1.0)
        self.assertEqual(sink._coerce_predicted("confidence", False), 0.0)

    def test_unknown_value_is_none(self) -> None:
        self.assertIsNone(sink._coerce_predicted("severity", "made-up"))
        self.assertIsNone(sink._coerce_predicted("confidence", "not a number"))
        self.assertIsNone(sink._coerce_predicted("severity", None))


class ValidationTests(unittest.TestCase):
    def test_unknown_role_raises(self) -> None:
        with self.assertRaises(ValueError):
            _run(sink.capture(
                role="nope",  # type: ignore[arg-type]
                output_type="severity", predicted="critical",
            ))

    def test_unknown_output_type_raises(self) -> None:
        with self.assertRaises(ValueError):
            _run(sink.capture(
                role="verify",
                output_type="nope",  # type: ignore[arg-type]
                predicted=0.5,
            ))


class CaptureRoutingTests(unittest.TestCase):
    def test_prediction_only_no_outcome(self) -> None:
        with mock.patch.object(sink, "_record_prediction", return_value=42) as m_pred, \
             mock.patch.object(sink, "_record_outcome") as m_out:
            pid = _run(sink.capture(
                role="verify", output_type="severity",
                predicted="high", project_id=7, subject_id="finding-1",
            ))
        self.assertEqual(pid, 42)
        m_pred.assert_called_once()
        # raw_predicted coerced to 0.75 for 'high'
        args, kwargs = m_pred.call_args
        self.assertEqual(args[0], "verify")
        self.assertEqual(args[1], "severity")
        self.assertAlmostEqual(args[2], 0.75)
        self.assertEqual(kwargs["project_id"], 7)
        self.assertEqual(kwargs["subject_id"], "finding-1")
        m_out.assert_not_called()

    def test_prediction_plus_outcome(self) -> None:
        with mock.patch.object(sink, "_record_prediction", return_value=101), \
             mock.patch.object(sink, "_record_outcome", return_value=202) as m_out:
            pid = _run(sink.capture(
                role="iso", output_type="confidence",
                predicted=0.82, outcome=1.0, audit_record_id=555,
            ))
        self.assertEqual(pid, 101)
        m_out.assert_called_once()
        out_args = m_out.call_args.args
        self.assertEqual(out_args[0], 101)         # prediction_id
        self.assertAlmostEqual(out_args[1], 1.0)   # observed
        self.assertEqual(out_args[2], "verify_pass")

    def test_metadata_threads_into_features(self) -> None:
        with mock.patch.object(sink, "_record_prediction", return_value=1) as m_pred, \
             mock.patch.object(sink, "_record_outcome"):
            _run(sink.capture(
                role="auditor", output_type="risk_band",
                predicted="medium_high",
                metadata={"model": "claude-sonnet-4-6", "layer": "iso_swarm"},
            ))
        features = m_pred.call_args.kwargs["features"]
        self.assertEqual(features["model"], "claude-sonnet-4-6")
        self.assertEqual(features["layer"], "iso_swarm")
        self.assertEqual(features["original_predicted"], "medium_high")

    def test_predicted_coercion_failure_returns_none_no_db(self) -> None:
        with mock.patch.object(sink, "_record_prediction") as m_pred, \
             mock.patch.object(sink, "_record_outcome") as m_out:
            pid = _run(sink.capture(
                role="verify", output_type="severity", predicted="bogus",
            ))
        self.assertIsNone(pid)
        m_pred.assert_not_called()
        m_out.assert_not_called()

    def test_prediction_db_failure_returns_none(self) -> None:
        with mock.patch.object(sink, "_record_prediction", return_value=None), \
             mock.patch.object(sink, "_record_outcome") as m_out:
            pid = _run(sink.capture(
                role="verify", output_type="confidence", predicted=0.5,
            ))
        self.assertIsNone(pid)
        m_out.assert_not_called()


class BatchTests(unittest.TestCase):
    def test_capture_many(self) -> None:
        with mock.patch.object(sink, "_record_prediction", return_value=7), \
             mock.patch.object(sink, "_record_outcome", return_value=8):
            ids = _run(sink.capture_many([
                dict(role="verify", output_type="severity", predicted="critical"),
                dict(role="iso", output_type="confidence", predicted=0.6),
                dict(role="auditor", output_type="risk_band", predicted="high"),
            ]))
        self.assertEqual(ids, [7, 7, 7])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
