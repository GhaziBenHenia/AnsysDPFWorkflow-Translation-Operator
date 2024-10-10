# - The first argument is the path to the directory where the plugin
#   is located.
# - The second argument is ``py_`` plus the name of the Python script.
# - The third argument is the name of the function used to record operators.
#

import os
from ansys.dpf import core as dpf
from ansys.dpf.core import examples

# Python plugins are not supported in process.
dpf.start_local_server(config=dpf.AvailableServerConfigs.GrpcServer)
#OR Use a specific server
#dpf.connect_to_server('ip_address', port)

operator_file_path = "DPFTranslationOperator.py"
operator_server_file_path = dpf.upload_file_in_tmp_folder(operator_file_path)
dpf.load_library(os.path.dirname(operator_server_file_path), "py_DPFTranslationOperator", "load_operators")