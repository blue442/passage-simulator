from passage.engine.orders import Orders
from passage.engine.state import PassageParams

# PassageParams.orders is a string forward reference (see state.py) to avoid a real import
# cycle: orders.py needs GeoPoint from state.py, so state.py cannot import orders.py at
# runtime. Resolve it once here, after both modules are loaded.
PassageParams.model_rebuild(_types_namespace={"Orders": Orders})
