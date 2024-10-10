import os
import re
from ansys.dpf import core as dpf
from ansys.dpf.core.custom_operator import CustomOperatorBase, record_operator
from ansys.dpf.core.operator_specification import CustomSpecification, SpecificationProperties, PinSpecification


# Function to capture operator IO (inputs/outputs) with names as keys
def get_operator_io(operator):
    operator_info = {"inputs": {}, "outputs": {}}
    
    # Capture inputs
    if operator.inputs:
        for pin_num in range(len(operator.inputs)):
            input_pin = operator.inputs.get_input(pin_num)
            if input_pin:
                operator_info["inputs"][input_pin.name] = {"pin_number": pin_num, "type": type(input_pin).__name__}

    # Capture outputs
    if operator.outputs:
        for pin_num in range(len(operator.outputs)):
            output_pin = operator.outputs.get_output(pin_num)
            if output_pin:
                operator_info["outputs"][output_pin.name] = {"pin_number": pin_num, "type": type(output_pin).__name__}
                
    return operator_info


# Function to execute and capture operators from script content
def execute_and_capture_operators(script_content):
    captured_globals = {}
    exec(script_content, captured_globals)

    # Capture all operators
    operators = {name: obj for name, obj in captured_globals.items() if isinstance(obj, dpf.Operator)}

    # Collect operator I/O information
    operator_io_dict = {}
    operator_names = []

    for name, operator in operators.items():
        operator_io_dict[name] = get_operator_io(operator)
        operator_names.append(name)

    return operator_io_dict, operator_names


# Function to generate the workflow script
def generate_workflow_script(operator_names):
    workflow_script = f'''
from ansys.dpf import core as dpf
workflow = dpf.Workflow()
workflow.add_operators([{', '.join(operator_names)}])
'''
    return workflow_script


# Function to execute the extended script with the workflow part and capture only the last workflow object
def execute_with_last_workflow(script_content, workflow_script):
    # Append the workflow script to the original script
    full_script = script_content + "\n" + workflow_script
    
    captured_globals = {}
    exec(full_script, captured_globals)

    # Capture only the last workflow object
    last_workflow_obj = None
    for name, obj in captured_globals.items():
        if isinstance(obj, dpf.Workflow):
            last_workflow_obj = obj  # We keep overwriting until the last workflow is found
    
    return last_workflow_obj


# Function to generate PyDPF script using Workflow_to_PyDPF_Generator operator
def generate_pydpf_script(workflow):
    # Instantiate the operator
    op = dpf.operators.utility.Workflow_to_PyDPF_Generator(
        workflow=workflow
    )
    
    # PyDPF script as a string
    result_pydpf_code = op.outputs.pydpf_code()
    
    return result_pydpf_code

# Function to convert the full PyDPF script to C++ code using regex
def convert_pydpf_to_cpp(pydpf_script, operator_io_dict):
    # Start the C++ code with necessary headers
    cpp_code = [
        '#include "dpf_api.h"',
        '#include "dpf_api_i.cpp"',
        ''
    ]

    # Regex patterns for operator creation, connections, and outputs in PyDPF
    operator_creation_pattern1 = r'(\w+)\s*=\s*ops\.(\w+)\.(\w+)\((.*)\)'  # For ops.utility.forward()
    operator_creation_pattern2 = r'(\w+)\s*=\s*dpf.Operator\("([^"]+)"\)'  # For dpf.Operator("logic::if")
    
    # 1. For logic_if_op_46.connect(0, forward_op_19, 0)
    operator_connection_pattern = r'(\w+)\.connect\((\d+),\s*(\w+),\s*(\d+)\)'
    
    # 2. For forward_op_19.inputs.any.connect(input)
    operator_connection_simple = r'(\w+)\.inputs\.(\w+)\.connect\((\w+)\)'
    
    # 3. For operator_name.inputs.input_name.connect(another_operator_name.outputs.output_name)
    operator_connection_with_output = r'(\w+)\.inputs\.(\w+)\.connect\((\w+)\.outputs\.(\w+)\)'

    # 4. For logic_if_op_37.connect(0, logic_if_37_input)
    operator_simple_connect_with_pin = r'(\w+)\.connect\((\d+),\s*(\w+)\)'

    # For output assignments like `my_output = op.outputs.some_output()`
    operator_output_pattern = r'(\w+)\s*=\s*(\w+)\.outputs\.(\w+)\(\)'

    # Process the script
    for line in pydpf_script.splitlines():
        # Check for operator creation pattern (Method 1)
        creation_match1 = re.match(operator_creation_pattern1, line.strip())
        # Check for operator creation pattern (Method 2)
        creation_match2 = re.match(operator_creation_pattern2, line.strip())
        # Check for operator connection patterns
        connection_match = re.match(operator_connection_pattern, line.strip())
        simple_connection_match = re.match(operator_connection_simple, line.strip())
        connection_with_output_match = re.match(operator_connection_with_output, line.strip())
        simple_connect_with_pin_match = re.match(operator_simple_connect_with_pin, line.strip())
        # Check for operator output patterns
        output_match = re.match(operator_output_pattern, line.strip())

        # Convert operator creation (Method 1) to C++ equivalent
        if creation_match1:
            operator_name, module_name, op_name, _ = creation_match1.groups()
            cpp_op_creation = f'ansys::dpf::Operator {operator_name}("{module_name}::{op_name}");'
            cpp_code.append(cpp_op_creation)

        # Convert operator creation (Method 2) to C++ equivalent
        elif creation_match2:
            operator_name, operator_type = creation_match2.groups()
            cpp_op_creation = f'ansys::dpf::Operator {operator_name}("{operator_type}");'
            cpp_code.append(cpp_op_creation)

        # Convert operator connection to C++ equivalent (e.g. logic_if_op_46.connect(0, forward_op_19, 0))
        elif connection_match:
            output_op, output_pin, input_op, input_pin = connection_match.groups()
            cpp_op_connection = f'{output_op}.connect({output_pin}, {input_op}, {input_pin});'
            cpp_code.append(cpp_op_connection)

        # Convert simple operator connection (e.g. forward_op_19.inputs.any.connect(input))
        elif simple_connection_match:
            output_op, input_pin, input_op = simple_connection_match.groups()
            cpp_op_connection = f'{output_op}.connect({input_op});'
            cpp_code.append(cpp_op_connection)

        # Convert operator connection with output (e.g. op1.inputs.x.connect(op2.outputs.x))
        elif connection_with_output_match:
            output_op, input_pin, input_op, output_pin = connection_with_output_match.groups()
            cpp_op_connection = f'{output_op}.connect({input_op}.getOutputFieldsContainer(0));'  # Assuming FieldsContainer and pin 0
            cpp_code.append(cpp_op_connection)

        # Convert simple operator connection with pin (e.g. logic_if_op_37.connect(0, logic_if_37_input))
        elif simple_connect_with_pin_match:
            output_op, output_pin, input_op = simple_connect_with_pin_match.groups()
            cpp_op_connection = f'{output_op}.connect({output_pin}, {input_op});'
            cpp_code.append(cpp_op_connection)

        # Convert operator outputs to C++ equivalent (e.g. my_output = op.outputs.some_output())
        elif output_match:
            output_name, operator_name, output_type = output_match.groups()
            operator_info = operator_io_dict.get(operator_name, {})
            output_pin = None
            cpp_output_type = None

            # Look up the pin number and type from captured operator I/O
            for name, output in operator_info.get('outputs', {}).items():
                if name == output_type:
                    output_pin = output['pin_number']
                    cpp_output_type = f"ansys::dpf::{output['type']}"

            if output_pin is not None and cpp_output_type:
                # Use the type after getOutput
                cpp_op_output = f'{cpp_output_type} {output_name} = {operator_name}.getOutput{output["type"]}({output_pin});'
                cpp_code.append(cpp_op_output)

        # For now I'm Ignoring lines without mappings
        else:
            continue

    # Join the generated C++ code into a single string
    return "\n".join(cpp_code)

# Main function that takes a PyDPF script and returns C++ code
def pydpf_to_cpp(script_content):
    # Step 1: Execute the script and capture operator information
    operator_io_dict, operator_names = execute_and_capture_operators(script_content)

    # Step 2: Generate the workflow script
    workflow_script = generate_workflow_script(operator_names)

    # Step 3: Execute the combined script (original + workflow) and capture only the last workflow
    last_workflow = execute_with_last_workflow(script_content, workflow_script)

    # Step 4: Generate the PyDPF script from the last workflow using the operator
    pydpf_code = generate_pydpf_script(last_workflow)

    # Step 5: Convert the generated PyDPF script to C++ code
    cpp_code = convert_pydpf_to_cpp(pydpf_code, operator_io_dict)

    return cpp_code

def parse_dpf_cpp_script(script_content):
    # Structure to store operator name and parameters
    operators = []
    
    # Regex pattern to find ansys::dpf::Operator declarations
    # We Look for: ansys::dpf::Operator <name>(<params>);
    pattern = r'ansys::dpf::Operator\s+(\w+)\s*\((.*?)\)\s*;'
    
    matches = re.findall(pattern, script_content)
    
    # Store the results in a list of dictionaries
    for match in matches:
        operator_name = match[0]  # The operator variable name
        operator_params = match[1]  # The string inside the parentheses (The operator name in DPF-core)
        operators.append({"name": operator_name, "params": operator_params})
    
    return operators

def generate_workflow_code(operators):
    # Generate C++ workflow object based on the operators
    workflow_code = "\n\n// Add operators to the workflow\n"
    workflow_code += "ansys::dpf::Workflow workflow;\n"
    
    for op in operators:
        workflow_code += f'workflow.addOperator("{op["name"]}", {op["name"]});\n'
    
    workflow_code += 'std::string workflow_id = workflow.record();\n'
    workflow_code += '#include <fstream>\nstd::ofstream outfile("workflow_id.txt", std::ofstream::trunc);\n'
    workflow_code += 'if (outfile.is_open()) {\noutfile << workflow_id;\noutfile.close();\n} else {\nstd::cerr << "Error: Unable to open file to write workflow_id" << std::endl;\nreturn 1;\n}'
    
    return workflow_code


def append_workflow_to_script(script_content, workflow_code):
    # Append the workflow code at the end of the script content
    return script_content + "\n" + workflow_code


def execute_cpp_script(output_file_path="CPP_DPF_Script_with_workflow.cpp"):
    #TODO: I need to imlement a method to execute a cpp process
    raise NotImplementedError("The function to execute a cpp script is not implemented yet!")


def process_dpf_cpp_script(script_content, output_file_path="CPP_DPF_Script_with_workflow.cpp"):
    # Step 1: Parse the script to find ansys::dpf::Operator declarations
    operators = parse_dpf_cpp_script(script_content)

    # Step 2: Generate the C++ workflow object with the detected operators
    workflow_code = generate_workflow_code(operators)

    # Step 3: Append the workflow code to the end of the script content
    appended_script = append_workflow_to_script(script_content, workflow_code)

    # Step 4: Save the appended script to a file to execute it
    with open(output_file_path, "w") as file:
        file.write(appended_script)

    # Step 5: Execute the workflow in cpp to record the workflow and get the ID
    execute_cpp_script(output_file_path="CPP_DPF_Script_with_workflow.cpp")


def get_pydpf_code_from_recorded_workflow():
    # Step 1: Read the recorded workflow ID from workflow_id.txt
    workflow_id_file = "workflow_id.txt"
    
    if not os.path.exists(workflow_id_file):
        raise FileNotFoundError(f"'{workflow_id_file}' not found.")
    
    with open(workflow_id_file, "r") as file:
        workflow_id = file.read().strip()

    # Step 2: Get the recorded workflow using the ID
    try:
        workflow = dpf.Workflow.get_recorded_workflow(workflow_id)
    except Exception as e:
        raise RuntimeError(f"Error retrieving the recorded workflow: {e}")

    # Step 3: Use Workflow_to_PyDPF_Generator to generate the PyDPF script
    op = dpf.operators.utility.Workflow_to_PyDPF_Generator(
        workflow=workflow
    )
    
    # Step 4: Retrieve the PyDPF script as a string
    result_pydpf_code = op.outputs.pydpf_code()
    
    # Step 5: Return the PyDPF script
    return result_pydpf_code



def process_dpf_script_based_on_language(script_content, target_language):
    if target_language == "CPP":
        # Call process_dpf_cpp_script to handle the C++ workflow
        process_dpf_cpp_script(script_content, output_file_path="CPP_DPF_Script_with_workflow.cpp")
        return (get_pydpf_code_from_recorded_workflow()) # Generate PyDPF code from the recorded workflow

    elif target_language == "CPython":
        # Call pydpf_to_cpp to handle the CPython to C++ translation
        return(pydpf_to_cpp(script_content))

    
    else:
        raise ValueError(f"Unsupported target language: {target_language}")


class DPFTranslationOperator(CustomOperatorBase):

    @property
    def name(self):
        return "dpf_translation_operator"

    @property
    def specification(self) -> CustomSpecification:
        spec = CustomSpecification()
        spec.description = "Converts DPF workflows between CPython and C++."

        # Input pins
        spec.inputs = {
            0: PinSpecification("workflow_str", [str], "A workflow script in CPython or C++ to be translated."),
            1: PinSpecification("target_language", [str], "Target language for translation ('CPython' or 'C++').")
        }

        # Output pins
        spec.outputs = {
            0: PinSpecification("translated_workflow", [str], "The translated workflow script.")
        }

        # Setting the category for this operator
        spec.properties = SpecificationProperties(category="utility")
        return spec

    def run(self):
        workflow_str = self.get_input(0, str)
        target_language = self.get_input(1, str)

        translated_script = process_dpf_script_based_on_language(workflow_str, target_language)

        self.set_output(0, translated_script)
        self.set_succeeded()

def load_operators(*args):
    record_operator(DPFTranslationOperator, *args)
