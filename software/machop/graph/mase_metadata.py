import logging
import os
import math
import time

import torch
import torch.fx
from torch import nn
from torch.fx import symbolic_trace

from .utils import get_module_by_name, vf

logger = logging.getLogger(__name__)


class MaseMetadata:
    """
    The metadata of a Mase node in a Mase graph describes the constraints of the
    node for any static analysis or possible transformation. The metadata has a
    tree structure, e.g.
    - Common
      - args -> []
         - name : name of the arg
           - type : type of the arg, e.g. fixed point or float
           - precision : format of the type, e.g. (10, 5)
           - size : size of the arg
      - results -> []
         - name : name of the result
           - type : type of the result, e.g. fixed point or float
           - precision : format of the type, e.g. (10, 5)
           - size : size of the result
    - Software
         - ???
    - Hardware
      - verilog_parameters -> {} : parameters need for customise the hardware module
      - toolchain -> str : tool chain for code generation, must be internal, external or HLS
      - module -> str : the name of the used hardware module
      - dependence_files -> [] : the dependent files for the generated module
    ...
    """

    # Hardware dict
    internal_layers = {nn.Linear: "linear", nn.ReLU: "relu"}
    # internal_layers = {}
    known_types = {"fixed", "float"}
    known_toolchain = {"INTERNAL", "EXTERNAL", "HLS"}

    def __init__(self, node=None, model=None):
        # Top-level model
        self.model = model
        # The target layer/module in the model
        self.module = get_module_by_name(model, node.target)
        # The type of the module
        self.type = type(self.module)
        # The fx node of the module in the fx graph of the model
        self.node = node
        self.parameters = {
            "common": {},
            "software": {},
            "hardware": {},
        }

    def init_common_parameters(self, parameters=None):
        """
        Init common parameters
        """
        if self.node.op == "call_module" or self.node.op == "call_function":
            if self.type in self.internal_layers:
                name = self.internal_layers[self.type]
                replace_fn = getattr(self, f"_init_common_parameters_{name}")
                replace_fn(parameters)
            else:
                logger.warning(f"{self.node} is not found in the internal library.")
                self._init_common_parameters(parameters)
        else:
            logger.warning(f"Not dealing with node for now: {self.node}")

    def init_software_parameters(self, parameters=None):
        """
        Init software parameters
        """
        if self.node.op == "call_module" or self.node.op == "call_function":
            if self.type in self.internal_layers:
                name = self.internal_layers[self.type]
                replace_fn = getattr(self, f"_init_software_parameters_{name}")
                replace_fn(parameters)
            else:
                logger.warning(f"{self.node} is not found in the internal library.")
                self._init_software_parameters(parameters)
        else:
            logger.warning(f"Not dealing with node for now: {self.node}")

    def init_hardware_parameters(self, parameters=None):
        """
        Init hardware parameters
        """
        if self.node.op == "call_module" or self.node.op == "call_function":
            if self.type in self.internal_layers:
                name = self.internal_layers[self.type]
                replace_fn = getattr(self, f"_init_hardware_parameters_{name}")
                replace_fn(parameters)
            else:
                logger.warning(f"{self.node} is not found in the internal library.")
                self._init_hardware_parameters(parameters)
        else:
            logger.warning(f"Not dealing with node for now: {self.node}")

    def verify(self):
        """
        Verify all the parameters
        """
        if self.node.op == "call_module" or self.node.op == "call_function":
            self._verify_parameters_general()
            if self.type in self.internal_layers:
                name = self.internal_layers[self.type]
                replace_fn = getattr(self, f"_verify_parameters_{name}")
                replace_fn()
            else:
                logger.warning(f"{self.node} is not found in the internal library.")
                self._verify_parameters_other()
        else:
            logger.warning(f"Not dealing with node for now: {self.node}")

    def _verify_parameters_general(self):
        """
        Verify general parameters for all the nodes
        """
        # Verify common parameters
        assert (
            "data_in" in self.parameters["common"]["args"].keys()
        ), f"Cannot find data_in in common.arg parameters. {self.node}"
        assert (
            "data_out" in self.parameters["common"]["results"].keys()
        ), f"Cannot find data_out in common.arg parameters. {self.node}"
        for arg, param in self.parameters["common"]["args"]:
            ## Valid type
            arg_type = param["type"]
            assert arg_type in self.known_types, f"Unknown type for {arg} : {arg_type}"
            ## Valid size
            arg_size = param["size"]
            assert arg_size, f"Unknown size for {arg} : {arg_size}"
            ## Data width must be greater than frac width
            if arg_type == "fixed":
                assert param["precision"][0] > 0, f"{arg} must have a positive width."
                assert (
                    param["precision"][0] >= param["precision"][1]
                ), f"{arg} must have a width greater than the frac width."
            elif arg_type == "float":
                assert (
                    param["precision"][0] == 32 or param["precision"][0] == 64
                ), f"{arg} must have a width of 32 or 64 as float."
            else:
                assert False, f"Unsupported arg type from toml. {param[type]}"
        assert (
            self.parameters["common"]["args"]["data_in"]["type"]
            == self.parameters["common"]["results"]["type"]
        ), "Input and out data type must match. "

        result_param = self.parameters["common"]["results"]["data_out"]
        result_type = result_param["type"]
        if result_type == "fixed":
            assert (
                result_param["precision"][0] > 0
            ), f"data_out must have a positive width."
            assert (
                result_param["precision"][0] >= result_param["precision"][1]
            ), f"data_out must have a width greater than the frac width."
        elif result_type == "float":
            assert (
                result_param["precision"][0] == 32 or result_param["precision"][0] == 64
            ), f"data_out must have a width of 32 or 64 as float."
        else:
            assert False, f"Unsupported arg type from toml. {param[type]}"
        assert result_param["size"], "Invalid out data size must match. "

        # Verify hardware parameters
        toolchain = self.parameters["hardware"]["toolchain"]
        assert (
            toolchain in self.known_toolchain
        ), f"Invalid parameter toolchain = {TARGET}. {self.node}"

    # ----------------------------------------------------------
    # Linear
    # ----------------------------------------------------------
    def _init_common_parameters_linear(self, parameters):
        self.parameters["common"]["args"] = {}
        for name, parameter in self.module.named_parameters():
            self.parameters["common"]["args"][name] = {
                "type": "float",
                "precision": [32],
                "size": parameter.shape,
            }
        assert hasattr(
            self.module, "in_features"
        ), f"Linear layer {self.node.name} does not have in features."
        assert hasattr(
            self.module, "out_features"
        ), f"Linear layer {self.node.name} does not have out features."
        self.parameters["common"]["args"]["data_in"] = {
            "type": "float",
            "precision": [32],
            "size": (
                1,
                self.module.in_features,
            ),
        }
        self.parameters["common"]["results"] = {
            "data_out": {
                "type": "float",
                "precision": [32],
                "size": (
                    1,
                    self.module.out_features,
                ),
            }
        }
        if parameters:
            self._update_common_parameters_linear(parameters)

    def _update_common_parameters_linear(self, parameters):
        """
        Toml format check. Example toml:
            ["node.name"]
            name = "integer"
            weight_width = 8
            weight_frac_width = 3
            data_in_width = 8
            data_in_frac_width = 5
            bias_width = 8
            bias_frac_width = 5
        """

        assert parameters
        expected_keys = [
            "weight_width",
            "weight_frac_width",
            "data_in_width",
            "data_in_frac_width",
            "bias_width",
            "bias_frac_width",
            "name",
        ]
        expected_keys.sort()
        input_keys = list(parameters.keys())
        input_keys.sort()
        if input_keys != expected_keys:
            assert False, f"""
{self.node.name}: Unexpected parameters found for linear, 
expect: {expected_keys}, 
actual keys: {input_keys}"""

        # Update common parameters
        arg_type = parameters["name"]
        for arg, param in self.parameters["common"]["args"].items():
            # TODO: Do we need a type for each arg?
            self.parameters["common"]["args"][arg]["type"] = arg_type
            if arg_type == "fixed":
                self.parameters["common"]["args"][arg]["precision"] = (
                    parameters[f"{arg}_width"],
                    parameters[f"{arg}_frac_width"],
                )
            else:
                assert False, "Unsupported arg type from toml. Only fixed is supported."
        # Assume data_out has the same type as data_in
        self.parameters["common"]["results"]["data_out"]["type"] = self.parameters[
            "common"
        ]["args"]["data_in"]["type"]
        if arg_type == "fixed":
            # Update the output precision based on the input precision - assume lossless
            # Output width = max(bias_width, data_in_width + weight_width + clog2(in_size)) + 1
            # Output frac width = max(bias_frac_width, data_in_frac_width + weight_frac_width)
            bias_width = self.parameters["common"]["args"]["bias"]["precision"][0]
            weight_width = self.parameters["common"]["args"]["weight"]["precision"][0]
            data_in_width = self.parameters["common"]["args"]["data_in"]["precision"][0]
            clog2_data_in_size = int(
                math.ceil(
                    math.log2(self.parameters["common"]["args"]["data_in"]["size"][1])
                )
            )
            bias_frac_width = self.parameters["common"]["args"]["bias"]["precision"][1]
            weight_frac_width = self.parameters["common"]["args"]["weight"][
                "precision"
            ][1]
            data_in_frac_width = self.parameters["common"]["args"]["data_in"][
                "precision"
            ][1]
            self.parameters["common"]["results"]["data_out"]["precision"] = (
                max(bias_width, weight_width + data_in_width + clog2_data_in_size) + 1,
                max(bias_frac_width, data_in_frac_width + weight_frac_width),
            )
        else:
            assert False, "Unsupported arg type from toml. Only fixed is supported."

    def _init_software_parameters_linear(self, parameters):
        """
        TODO
        """

    def _init_hardware_parameters_linear(self, parameters):
        arg_type = self.parameters["common"]["args"]["data_in"]["type"]
        if arg_type == "fixed":
            self.parameters["hardware"] = {
                "verilog_parameters": {
                    "IN_WIDTH": self.parameters["common"]["args"]["data_in"][
                        "precision"
                    ][0],
                    "IN_FRAC_WIDTH": self.parameters["common"]["args"]["data_in"][
                        "precision"
                    ][1],
                    "WEIGHT_WIDTH": self.parameters["common"]["args"]["weight"][
                        "precision"
                    ][0],
                    "WEIGHT_FRAC_WIDTH": self.parameters["common"]["args"]["weight"][
                        "precision"
                    ][1],
                    "HAS_BIAS": int("bias" in self.parameters["common"]["args"].keys()),
                    "BIAS_WIDTH": self.parameters["common"]["args"]["bias"][
                        "precision"
                    ][0],
                    "BIAS_FRAC_WIDTH": self.parameters["common"]["args"]["bias"][
                        "precision"
                    ][1],
                    # Fully unrolled by default value
                    "IN_SIZE": self.parameters["common"]["args"]["data_in"]["size"][1],
                    "IN_DEPTH": 1,
                    "PARALLELISM": self.parameters["common"]["results"]["data_out"][
                        "size"
                    ][1],
                    # WEIGHT_SIZE == IN_SIZE
                    "WEIGHT_SIZE": self.parameters["common"]["args"]["data_in"]["size"][
                        1
                    ],
                    # OUT_WIDTH == IN_WIDTH + WEIGHT_WIDTH + $clog2(IN_SIZE) + $clog2(IN_DEPTH) + HAS_BIAS
                    "OUT_WIDTH": self.parameters["common"]["results"]["data_out"][
                        "precision"
                    ][0],
                    # OUT_SIZE == PARALLELISM
                    "OUT_SIZE": self.parameters["common"]["results"]["data_out"][
                        "size"
                    ][1],
                    # BIAS_SIZE == PARALLELISM
                    "BIAS_SIZE": self.parameters["common"]["results"]["data_out"][
                        "size"
                    ][1],
                },
                "toolchain": "INTERNAL",
                "module": "fixed_linear",
                "dependence_files": [
                    "common/fixed_cast.sv",
                    "common/fixed_dot_product.sv",
                    "common/fixed_vector_mult.sv",
                    "common/register_slice.sv",
                    "common/fixed_accumulator.sv",
                    "common/fixed_adder_tree.sv",
                    "common/fixed_adder_tree_layer.sv",
                    "common/fixed_mult.sv",
                    "common/join2.sv",
                    "linear/fixed_linear.sv",
                ],
            }
        else:
            assert (
                False
            ), f"Unsupported arg type from toml. Only fixed is supported : {arg_type}"

        if parameters:
            self._update_hardware_parameters_linear(parameters)

    def _update_hardware_parameters_linear(self, parameters):
        assert parameters
        assert (
            False
        ), "External toml for updating hardware parameters of linear op is not supproted."

    def _verify_parameters_linear(self):
        # Verify common parameters
        assert (
            self.parameters["common"]["args"]["data_in"]["size"][1]
            == self.parameters["common"]["args"]["weight"]["size"][0]
        ), "Input size does not match with the weight row size."
        assert (
            self.parameters["common"]["results"]["data_out"]["size"][1]
            == self.parameters["common"]["args"]["weight"]["size"][1]
        ), "Output size does not match with the weight column size."

        # Verify hardware parameters
        data_in_param = self.parameters["common"]["data_in"]
        if data_in_param["type"] == "fixed":
            assert (
                self.parameters["hardware"]["verilog_parameters"]["IN_WIDTH"]
                == data_in_param["precision"][0]
            )
            assert (
                self.parameters["hardware"]["verilog_parameters"]["IN_FRAC_WIDTH"]
                == data_in_param["precision"][1]
            )
            weight_param = self.parameters["common"]["weight"]
            assert (
                self.parameters["hardware"]["verilog_parameters"]["WEIGHTWIDTH"]
                == weight_param["precision"][0]
            )
            assert (
                self.parameters["hardware"]["verilog_parameters"]["WEIGHTFRAC_WIDTH"]
                == weight_param["precision"][1]
            )
            bias_param = self.parameters["common"]["bias"]
            assert (
                self.parameters["hardware"]["verilog_parameters"]["BIAS_WIDTH"]
                == bias_param["precision"][0]
            )
            assert (
                self.parameters["hardware"]["verilog_parameters"]["BIAS_FRAC_WIDTH"]
                == bias_param["precision"][1]
            )
            assert self.parameters["hardware"]["verilog_parameters"]["IN_SIZE"] > 0
            assert self.parameters["hardware"]["verilog_parameters"]["IN_DEPTH"] > 0
            assert (
                self.parameters["hardware"]["verilog_parameters"]["IN_DEPTH"]
                * self.parameters["hardware"]["verilog_parameters"]["IN_SIZE"]
                == data_in_param["size"][1]
            )
            assert self.parameters["hardware"]["verilog_parameters"]["PARALLELISM"] > 0
            assert self.parameters["hardware"]["verilog_parameters"]["HAS_BIAS"] in [
                0,
                1,
            ], f"Invalid parameter HAS_BIAS = {HAS_BIAS}. {self.node}"
            # WEIGHT_SIZE == IN_SIZE
            assert (
                self.parameters["hardware"]["verilog_parameters"]["WEIGHT_SIZE"]
                == self.parameters["hardware"]["verilog_parameters"]["IN_SIZE"]
            )
            # OUT_WIDTH == IN_WIDTH + WEIGHT_WIDTH + $clog2(IN_SIZE) + $clog2(IN_DEPTH) + HAS_BIAS
            assert (
                self.parameters["common"]["results"]["data_out"]["precision"][0]
                == self.parameters["hardware"]["verilog_parameters"]["OUT_WIDTH"]
            )
            # OUT_SIZE == PARALLELISM
            assert (
                self.parameters["hardware"]["verilog_parameters"]["OUT_SIZE"]
                == self.parameters["hardware"]["verilog_parameters"]["PARALLELISM"]
            )
            # BIAS_SIZE == PARALLELISM
            assert (
                self.parameters["hardware"]["verilog_parameters"]["BIAS_SIZE"]
                == self.parameters["hardware"]["verilog_parameters"]["PARALLELISM"]
            )
        else:
            assert False, "Unsupported arg type from toml. Only fixed is supported."

    # ----------------------------------------------------------
    # ReLU
    # ----------------------------------------------------------
    def _init_common_parameters_relu(self, parameters):
        node_name = vf(self.node.name)
        # Common parameters
        self.parameters["common"]["args"] = {}
        for name, parameter in self.module.named_parameters():
            self.parameters["common"]["args"][name] = {
                "type": "float",
                "precision": (32),
                "size": parameter.shape,
            }

        # TEMP: Relu does not have in/out features. Try to fetch from the input nodes
        nodes_in = self.node.args
        nodes_out = list(self.node.users.keys())
        assert len(nodes_in) == 1, f"Relu {self.node.name} has {len(nodes_in)} inputs."
        assert (
            len(nodes_out) == 1
        ), f"Relu {self.node.name} has {len(nodes_out)} outputs."
        node_in = nodes_in[0]
        node_out = nodes_out[0]
        in_features = (
            node_in.meta.module.out_features
            if hasattr(node_in.meta.module, "out_features")
            else -1
        )
        out_features = (
            node_out.meta.module.in_features
            if hasattr(node_out.meta.module, "in_features")
            else -1
        )
        if in_features != -1 and out_features != -1:
            assert (
                in_features == out_features
            ), f"Relu's input ({node_in.name}) and output ({node_out.name}) have different features: {in_features}, {out_features}."
        features = max(in_features, out_features)

        self.parameters["common"]["args"]["data_in"] = {
            "type": "fixed",
            "precision": (32, 0),
            "size": (1, features),
        }
        self.parameters["common"]["results"] = {
            "data_out": {
                "type": "fixed",
                "precision": (32, 0),
                "size": (
                    1,
                    features,
                ),
            }
        }
        if parameters:
            self._update_common_parameters_relu(parameters)

    def _update_common_parameters_relu(self, parameters):
        """
        Toml format check. Example toml:
            ["node.name"]
            name = "integer"
            data_in_width = 8
            data_in_frac_width = 5
        """

        assert parameters
        expected_keys = [
            "data_in_width",
            "data_in_frac_width",
            "name",
        ].sort()
        input_keys = list(parameters.keys()).sort()
        if input_keys != expected_keys:
            assert False, f"""
{node_name}: Unexpected parameters found for linear, 
expect: {expected_keys}, 
actual keys: {input_keys}"""

        # Update common parameters
        arg_type = parameters["name"]
        for arg, param in self.parameters["common"]["args"].items():
            # TODO: Do we need a type for each arg?
            self.parameters["common"]["args"][arg]["type"] = arg_type
            if arg_type == "fixed":
                self.parameters["common"]["args"][arg]["precision"] = (
                    parameters[f"{arg}_width"],
                    parameters[f"{arg}_frac_width"],
                )
            else:
                assert False, "Unsupported arg type from toml. Only fixed is supported."
        # Assume data_out has the same type as data_in
        self.parameters["common"]["results"]["data_out"]["type"] = self.parameters[
            "common"
        ]["args"]["data_in"]["type"]
        if arg_type == "fixed":
            # Update the output precision based on the input precision - assume lossless
            # Output width = data_in_width
            # Output frac width = data_in_frac_width
            data_in_width = self.parameters["common"]["args"]["data_in"]["precision"][0]
            data_in_frac_width = self.parameters["common"]["args"]["data_in"][
                "precision"
            ][1]
            self.parameters["common"]["results"]["data_out"]["precision"] = (
                data_in_width,
                data_in_frac_width,
            )
        else:
            assert False, "Unsupported arg type from toml. Only fixed is supported."

    def _init_software_parameters_relu(self, parameters):
        """
        TODO
        """

    def _init_hardware_parameters_relu(self, parameters):
        if self.parameters["common"]["args"]["data_in"]["type"] == "fixed":
            self.parameters["hardware"] = {
                "verilog_parameters": {
                    "IN_SIZE": 1,
                    "IN_FRAC_WIDTH": self.parameters["common"]["args"]["data_in"][
                        "precision"
                    ][1],
                    "IN_WIDTH": self.parameters["common"]["args"]["data_in"][
                        "precision"
                    ][0],
                    # OUT = IN
                    "OUT_SIZE": 1,
                    "OUT_FRAC_WIDTH": self.parameters["common"]["args"]["data_in"][
                        "precision"
                    ][1],
                    "OUT_WIDTH": self.parameters["common"]["args"]["data_in"][
                        "precision"
                    ][0],
                },
                "toolchain": "INTERNAL",
                "module": "fixed_relu",
                "dependence_files": ["activations/fixed_relu.sv"],
            }
        else:
            assert False, "Unsupported arg type from toml. Only fixed is supported."
        if parameters:
            self._update_hardware_parameters_relu(parameters)

    def _update_hardware_parameters_relu(self, parameters):
        assert parameters
        assert (
            False
        ), "External toml for updating hardware parameters of relu op is not supproted."

    def _verify_parameters_relu(self):
        # Verify common parameters

        # Verify hardware parameters
        data_in_param = self.parameters["common"]["data_in"]
        if data_in_param["type"] == "fixed":
            assert (
                self.parameters["hardware"]["verilog_parameters"]["IN_WIDTH"]
                == data_in_param["precision"][0]
            )
            assert (
                self.parameters["hardware"]["verilog_parameters"]["IN_FRAC_WIDTH"]
                == data_in_param["precision"][1]
            )
            assert self.parameters["hardware"]["verilog_parameters"]["IN_SIZE"] > 0
            assert (
                self.parameters["hardware"]["verilog_parameters"]["IN_WIDTH"]
                == self.parameters["hardware"]["verilog_parameters"]["OUT_WIDTH"]
            )
            assert (
                self.parameters["hardware"]["verilog_parameters"]["IN_FRAC_WIDTH"]
                == self.parameters["hardware"]["verilog_parameters"]["OUT_FRAC_WIDTH"]
            )
            assert (
                self.parameters["hardware"]["verilog_parameters"]["IN_SIZE"]
                == self.parameters["hardware"]["verilog_parameters"]["OUT_SIZE"]
            )
        else:
            assert False, "Unsupported arg type from toml. Only fixed is supported."

    # ----------------------------------------------------------
    # Other
    # ----------------------------------------------------------
    def _init_common_parameters_other(self, parameters):
        self.parameters["common"]["args"] = {}
        for name, parameter in self.module.named_parameters():
            self.parameters["common"]["args"][name] = {
                "type": "fixed",
                "precision": (32, 0),
                "size": parameter.shape,
            }

        in_features = 0
        if hasattr(self.module, "in_features"):
            in_features = self.module.in_features
        else:
            nodes_in = self.node.args
            assert (
                len(nodes_in) == 1
            ), f"Module {self.node.name} has {len(nodes_in)} inputs."
            node_in = nodes_in[0]
            if hasattr(node_in.meta.module, "out_features"):
                in_features = node_in.meta.module.out_features
        assert in_features, f"Cannot find the in features for module {self.node.name}"

        out_features = 0
        if hasattr(self.module, "out_features"):
            out_features = self.module.out_features
        else:
            nodes_out = list(self.node.users.keys())
            assert (
                len(nodes_out) == 1
            ), f"Module {self.node.name} has {len(nodes_out)} outputs."
            node_out = nodes_out[0]
            if hasattr(node_out.meta.module, "in_features"):
                out_features = node_out.meta.module.in_features
        assert out_features, f"Cannot find the out features for module {self.node.name}"

        self.parameters["common"]["args"] = {
            "data_in": {
                "type": "fixed",
                "precision": (32, 0),
                "size": (
                    1,
                    in_features,
                ),
            }
        }
        self.parameters["common"]["results"] = {
            "data_out": {
                "type": "fixed",
                "precision": (32, 0),
                "size": (
                    1,
                    out_features,
                ),
            }
        }

    def _init_software_parameters_other(self, parameters):
        """
        TODO
        """

    def _init_hardware_parameters_other(self, parameters):
        self.parameters["hardware"]["verilog_parameters"] = {}
        self.parameters["hardware"]["toolchain"] = "HLS"
        self.parameters["hardware"]["module"] = node_name
        self.parameters["hardware"]["dependence_files"] = []

    def _verify_parameters_other(self):
        return
