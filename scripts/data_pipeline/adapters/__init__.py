from .cnc_tool_wear import CNCToolWearAdapter
from .industrial_maintenance import IndustrialMaintenanceAdapter
from .predictive_maintenance import PredictiveMaintenanceAdapter
from .steel_faults import SteelFaultsAdapter


ADAPTERS = {
    "predictive_maintenance": PredictiveMaintenanceAdapter,
    "cnc_tool_wear": CNCToolWearAdapter,
    "steel_faults": SteelFaultsAdapter,
    "industrial_maintenance": IndustrialMaintenanceAdapter,
}

