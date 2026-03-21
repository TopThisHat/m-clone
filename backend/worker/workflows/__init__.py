# Import workflow modules so their @registry.register decorators execute
from worker.workflows import validation  # noqa: F401
from worker.workflows import research    # noqa: F401
from worker.workflows import attribute_clustering  # noqa: F401
from worker.workflows import kg_promotion  # noqa: F401
