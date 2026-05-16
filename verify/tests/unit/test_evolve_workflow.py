"""EvolveWorkflow registration."""

from tron.workflows.evolve_workflow import EvolveWorkflow


def test_evolve_workflow_defn():
    assert EvolveWorkflow.__name__ == "EvolveWorkflow"
