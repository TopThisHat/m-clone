# Import workflow modules so their @registry.register decorators execute.
# Each module is imported individually so a failure names the exact culprit.
import importlib

_WORKFLOW_MODULES = [
    "worker.workflows.validation",
    "worker.workflows.research",
    "worker.workflows.attribute_clustering",
    "worker.workflows.kg_promotion",
]

for _module in _WORKFLOW_MODULES:
    try:
        importlib.import_module(_module)
    except Exception as exc:
        raise RuntimeError(f"Failed to import workflow module '{_module}'") from exc
