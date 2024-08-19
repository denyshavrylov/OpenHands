import argparse
import os
import pathlib
import platform
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, fields
from enum import Enum
from types import UnionType
from typing import Any, ClassVar, get_args, get_origin

import toml
from dotenv import load_dotenv

from openhands.core import logger
from openhands.core.utils import SingletonABCMeta

load_dotenv()


LLM_SENSITIVE_FIELDS = ['api_key', 'aws_access_key_id', 'aws_secret_access_key']
_DEFAULT_AGENT = 'CodeActAgent'
_MAX_ITERATIONS = 100


@dataclass
class BaseConfig(ABC):
    @classmethod
    @abstractmethod
    def load_from_env(cls, env_dict: dict[str, str]) -> 'BaseConfig':
        pass

    @classmethod
    @abstractmethod
    def load_from_toml(cls, toml_config: dict) -> Any:
        pass

    def defaults_to_dict(self) -> dict:
        result = {}
        for f in fields(self):
            result[f.name] = get_field_info(f)
        return result

    @staticmethod
    def _cast_value(field_type: type, value: str) -> Any:
        if field_type is bool:
            return str(value).lower() in ['true', '1']
        if get_origin(field_type) is UnionType:
            non_none_type = next(
                (t for t in get_args(field_type) if t is not type(None)), None
            )
            return non_none_type(value) if non_none_type else value
        return field_type(value)

    def __str__(self):
        attr_str = []
        for f in fields(self):
            attr_name = f.name
            attr_value = getattr(self, f.name)
            attr_str.append(f'{attr_name}={repr(attr_value)}')
        return f"{self.__class__.__name__}({', '.join(attr_str)})"

    def __repr__(self):
        return self.__str__()


@dataclass
class LLMConfig(BaseConfig):
    """Configuration for the LLM model.

    Attributes:
        model: The model to use.
        api_key: The API key to use.
        base_url: The base URL for the API. This is necessary for local LLMs. It is also used for Azure embeddings.
        api_version: The version of the API.
        aws_access_key_id: The AWS access key ID.
        aws_secret_access_key: The AWS secret access key.
        aws_region_name: The AWS region name.
        num_retries: The number of retries to attempt.
        retry_multiplier: The multiplier for the exponential backoff.
        retry_min_wait: The minimum time to wait between retries, in seconds. This is exponential backoff minimum. For models with very low limits, this can be set to 15-20.
        retry_max_wait: The maximum time to wait between retries, in seconds. This is exponential backoff maximum.
        timeout: The timeout for the API.
        max_message_chars: The approximate max number of characters in the content of an event included in the prompt to the LLM. Larger observations are truncated.
        temperature: The temperature for the API.
        top_p: The top p for the API.
        custom_llm_provider: The custom LLM provider to use. This is undocumented in openhands, and normally not used. It is documented on the litellm side.
        max_input_tokens: The maximum number of input tokens. Note that this is currently unused, and the value at runtime is actually the total tokens in OpenAI (e.g. 128,000 tokens for GPT-4).
        max_output_tokens: The maximum number of output tokens. This is sent to the LLM.
        input_cost_per_token: The cost per input token. This will available in logs for the user to check.
        output_cost_per_token: The cost per output token. This will available in logs for the user to check.
        ollama_base_url: The base URL for the OLLAMA API.
        drop_params: Drop any unmapped (unsupported) params without causing an exception.
    """

    model: str = 'gpt-4o'
    api_key: str | None = None
    base_url: str | None = None
    api_version: str | None = None
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_region_name: str | None = None
    num_retries: int = 10
    retry_multiplier: float = 2
    retry_min_wait: int = 3
    retry_max_wait: int = 300
    timeout: int | None = None
    max_message_chars: int = 10_000  # maximum number of characters in an observation's content when sent to the llm
    temperature: float = 0
    top_p: float = 0.5
    custom_llm_provider: str | None = None
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    input_cost_per_token: float | None = None
    output_cost_per_token: float | None = None
    ollama_base_url: str | None = None
    drop_params: bool | None = None
    memory_summarization_fraction: float = 0.75

    @classmethod
    def load_from_env(cls, env_dict: dict[str, str]) -> 'LLMConfig':
        config = cls()
        for f in fields(cls):
            env_var_name = f'LLM_{f.name.upper()}'
            if env_var_name in env_dict:
                value = env_dict[env_var_name]
                if value:
                    setattr(config, f.name, cls._cast_value(f.type, value))
        return config

    @classmethod
    def load_from_toml(cls, toml_config: dict | None) -> dict[str, 'LLMConfig']:
        llm_configs = {}
        default_config = cls()

        if toml_config is None:
            # nothing to read, return default llm
            llm_configs['llm'] = default_config
            return llm_configs

        # Load default [llm] section if it exists
        llm_section_dict = toml_config.get('llm', {})
        non_dict_fields = {
            k: v for k, v in llm_section_dict.items() if not isinstance(v, dict)
        }
        default_config = cls(**non_dict_fields)
        llm_configs['llm'] = default_config

        # Load custom LLM configs, falling back to default for unspecified attributes
        for key, value in toml_config.get('llm', {}).items():
            if key != 'llm' and isinstance(value, dict):
                logger.openhands_logger.debug(f'Loading custom llm config for {key}')
                # Create a new config, starting with default values
                custom_config = cls(**default_config.__dict__)
                # Update with custom values
                custom_config.__dict__.update(value)
                llm_configs[key] = custom_config

        return llm_configs

    def to_safe_dict(self):
        """Return a dict with the sensitive fields replaced with ******."""
        ret = self.__dict__.copy()
        for k, v in ret.items():
            if k in LLM_SENSITIVE_FIELDS:
                ret[k] = '******' if v else None
        return ret

    def __str__(self):
        attr_str = []
        for f in fields(self):
            attr_name = f.name
            attr_value = getattr(self, f.name)

            if attr_name in LLM_SENSITIVE_FIELDS:
                attr_value = '******' if attr_value else None

            attr_str.append(f'{attr_name}={repr(attr_value)}')

        return f"LLMConfig({', '.join(attr_str)})"

    def __repr__(self):
        return self.__str__()


@dataclass
class MemoryConfig(BaseConfig):
    """Configuration for the memory and embeddings.

    Attributes:
        embedding_model: The embedding model to use.
        base_url: The base URL for the embedding API.
        embedding_deployment_name: The name of the deployment for the embedding API. This is used for Azure OpenAI.
        api_key: The API key to use for embeddings.
        base_url: The base URL for the API. This is necessary for local embeddings or Azure.
        api_version: The version of the API.
    """

    embedding_model: str = 'local'
    base_url: str | None = None
    embedding_deployment_name: str | None = None
    api_key: str | None = None
    api_version: str | None = None

    @classmethod
    def load_from_env(cls, env_dict: dict[str, str]) -> 'MemoryConfig':
        config = cls()
        for f in fields(cls):
            env_var_name = f'MEMORY_{f.name.upper()}'
            if env_var_name in env_dict:
                value = env_dict[env_var_name]
                if value:
                    setattr(config, f.name, cls._cast_value(f.type, value))
        return config

    @classmethod
    def load_from_toml(cls, toml_config: dict | None) -> dict[str, 'MemoryConfig']:
        memory_configs = {}
        default_config = cls()

        if toml_config is None:
            # nothing to read, return default memory
            memory_configs['memory'] = default_config
            return memory_configs

        # Load default [memory] section if it exists
        memory_section_dict = toml_config.get('memory', {})
        non_dict_fields = {
            k: v for k, v in memory_section_dict.items() if not isinstance(v, dict)
        }
        default_config = cls(**non_dict_fields)
        memory_configs['memory'] = default_config

        # Load custom memory configs, falling back to default for unspecified attributes
        for key, value in toml_config.get('memory', {}).items():
            if key != 'memory' and isinstance(value, dict):
                logger.openhands_logger.debug(f'Loading custom memory config for {key}')
                # Create a new config, starting with default values
                custom_config = cls(**default_config.__dict__)
                # Update with custom values
                custom_config.__dict__.update(value)
                memory_configs[key] = custom_config

        return memory_configs


@dataclass
class AgentConfig(BaseConfig):
    """Configuration for the agent.

    Attributes:
        memory_enabled: Whether long-term memory (embeddings) is enabled.
        memory_max_threads: The maximum number of threads indexing at the same time for embeddings.
        llm_config: The name of the llm config to use or an actual LLMConfig object. If specified, this will override global llm config.
        memory_config: The name of the memory config to use or an actual MemoryConfig object. If specified, this will override global memory config.
    """

    memory_enabled: bool = False
    memory_max_threads: int = 2
    llm_config: str | LLMConfig | None = None
    memory_config: str | MemoryConfig | None = None

    def get_memory_config(self, app_config: 'AppConfig') -> MemoryConfig:
        if isinstance(self.memory_config, MemoryConfig):
            return self.memory_config
        elif isinstance(self.memory_config, str):
            return app_config.get_memory_config(self.memory_config)
        return app_config.get_memory_config()

    def get_llm_config(self, app_config: 'AppConfig') -> LLMConfig:
        if isinstance(self.llm_config, LLMConfig):
            return self.llm_config
        elif isinstance(self.llm_config, str):
            return app_config.get_llm_config(self.llm_config)
        return app_config.get_llm_config()

    @classmethod
    def load_from_env(cls, env_dict: dict[str, str]) -> 'AgentConfig':
        config = cls()
        for f in fields(cls):
            if f.name in ['llm_config', 'memory_config']:
                continue  # custom configs like llm per agent are not supported in env
            env_var_name = f'AGENT_{f.name.upper()}'
            if env_var_name in env_dict:
                value = env_dict[env_var_name]
                if value:
                    setattr(config, f.name, cls._cast_value(f.type, value))

        return config

    @classmethod
    def load_from_toml(cls, toml_config: dict | None) -> dict[str, 'AgentConfig']:
        agent_configs = {}
        default_config = cls()

        if toml_config is None:
            # nothing to read, return default agent
            agent_configs['agent'] = default_config
            return agent_configs

        # Load default [agent] section if it exists
        agent_section_dict = toml_config.get('agent', {})
        non_dict_fields = {
            k: v for k, v in agent_section_dict.items() if not isinstance(v, dict)
        }
        default_config = cls(**non_dict_fields)

        # Ensure there is always a default 'agent' config
        agent_configs['agent'] = default_config

        # Load custom Agent configs
        for key, value in toml_config.get('agent', {}).items():
            if key != 'agent' and isinstance(value, dict):
                logger.openhands_logger.debug(f'Loading custom agent config for {key}')
                # Create a new config, starting with default values
                custom_config = cls(**default_config.__dict__)
                # Update with custom values
                custom_config.__dict__.update(value)
                agent_configs[key] = custom_config

        return agent_configs


@dataclass
class SecurityConfig(BaseConfig, metaclass=SingletonABCMeta):
    """Configuration for security related functionalities.

    Attributes:
        confirmation_mode: Whether to enable confirmation mode.
        security_analyzer: The security analyzer to use.
    """

    confirmation_mode: bool = False
    security_analyzer: str | None = None

    @classmethod
    def load_from_env(cls, env_dict: dict[str, str]) -> 'SecurityConfig':
        config = cls()
        for f in fields(cls):
            env_var_name = f'SECURITY_{f.name.upper()}'
            if env_var_name in env_dict:
                value = env_dict[env_var_name]
                if value:
                    setattr(config, f.name, cls._cast_value(f.type, value))
        return config

    @classmethod
    def load_from_toml(cls, toml_config: dict | None) -> 'SecurityConfig':
        if toml_config is None:
            return cls()
        if 'security' in toml_config:
            return cls(**toml_config['security'])
        return cls()


@dataclass
class SandboxConfig(BaseConfig, metaclass=SingletonABCMeta):
    """Configuration for the sandbox.

    Attributes:
        api_hostname: The hostname for the EventStream Runtime API.
        container_image: The container image to use for the sandbox.
        user_id: The user ID for the sandbox.
        timeout: The timeout for the sandbox.
        enable_auto_lint: Whether to enable auto-lint.
        use_host_network: Whether to use the host network.
        initialize_plugins: Whether to initialize plugins.
        od_runtime_extra_deps: The extra dependencies to install in the runtime image (typically used for evaluation).
            This will be rendered into the end of the Dockerfile that builds the runtime image.
            It can contain any valid shell commands (e.g., pip install numpy).
            The path to the interpreter is available as $OD_INTERPRETER_PATH,
            which can be used to install dependencies for the OD-specific Python interpreter.
        od_runtime_startup_env_vars: The environment variables to set at the launch of the runtime.
            This is a dictionary of key-value pairs.
            This is useful for setting environment variables that are needed by the runtime.
            For example, for specifying the base url of website for browsergym evaluation.
        browsergym_eval_env: The BrowserGym environment to use for evaluation.
            Default is None for general purpose browsing. Check evaluation/miniwob and evaluation/webarena for examples.
    """

    api_hostname: str = 'localhost'
    container_image: str = 'nikolaik/python-nodejs:python3.11-nodejs22'  # default to nikolaik/python-nodejs:python3.11-nodejs22 for eventstream runtime
    user_id: int = os.getuid() if hasattr(os, 'getuid') else 1000
    timeout: int = 120
    enable_auto_lint: bool = (
        False  # once enabled, OpenHands would lint files after editing
    )
    use_host_network: bool = False
    initialize_plugins: bool = True
    od_runtime_extra_deps: str | None = None
    od_runtime_startup_env_vars: dict[str, str] = field(default_factory=dict)
    browsergym_eval_env: str | None = None

    @classmethod
    def load_from_env(cls, env_dict: dict[str, str]) -> 'SandboxConfig':
        config = cls()
        for f in fields(cls):
            env_var_name = f'SANDBOX_{f.name.upper()}'
            if env_var_name in env_dict:
                value = env_dict[env_var_name]
                if value:
                    setattr(config, f.name, cls._cast_value(f.type, value))
        return config

    @classmethod
    def load_from_toml(cls, toml_config: dict | None) -> 'SandboxConfig':
        sandbox_config = (
            cls()
        )  # This will either create a new instance or return the existing one

        if toml_config is None:
            return sandbox_config

        # First, migrate old sandbox configs from [core] section
        if 'core' in toml_config:
            core_config = toml_config['core']
            keys_to_migrate = [key for key in core_config if key.startswith('sandbox_')]
            for key in keys_to_migrate:
                new_key = key.replace('sandbox_', '')
                if hasattr(sandbox_config, new_key):
                    setattr(sandbox_config, new_key, core_config[key])
                else:
                    logger.openhands_logger.warning(f'Unknown sandbox config: {key}')

        # Then, override with new-style [sandbox] section if it exists
        if 'sandbox' in toml_config and isinstance(toml_config['sandbox'], dict):
            # Use the singleton's update mechanism
            cls(**toml_config['sandbox'])

        return sandbox_config


class UndefinedString(str, Enum):
    UNDEFINED = 'UNDEFINED'


@dataclass
class AppConfig(BaseConfig, metaclass=SingletonABCMeta):
    """Configuration for the app.

    Attributes:
        llms: A dictionary of name -> LLM configuration. Default config is under 'llm' key.
        memories: A dictionary of name -> Memory configuration. Default config is under 'memory' key.
        agents: A dictionary of name -> Agent configuration. Default config is under 'agent' key.
        memories: A dictionary of name -> Memory configuration. Default config is under 'memory' key.
        default_agent: The name of the default agent to use.
        sandbox: The sandbox configuration.
        runtime: The runtime environment.
        file_store: The file store to use.
        file_store_path: The path to the file store.
        workspace_base: The base path for the workspace. Defaults to ./workspace as an absolute path.
        workspace_mount_path: The path to mount the workspace. This is set to the workspace base by default.
        workspace_mount_path_in_sandbox: The path to mount the workspace in the sandbox. Defaults to /workspace.
        workspace_mount_rewrite: The path to rewrite the workspace mount path to.
        cache_dir: The path to the cache directory. Defaults to /tmp/cache.
        run_as_openhands: Whether to run as openhands.
        max_iterations: The maximum number of iterations.
        max_budget_per_task: The maximum budget allowed per task, beyond which the agent will stop.
        e2b_api_key: The E2B API key.
        disable_color: Whether to disable color. For terminals that don't support color.
        debug: Whether to enable debugging.
        enable_cli_session: Whether to enable saving and restoring the session when run from CLI.
        file_uploads_max_file_size_mb: Maximum file size for uploads in megabytes. 0 means no limit.
        file_uploads_restrict_file_types: Whether to restrict file types for file uploads. Defaults to False.
        file_uploads_allowed_extensions: List of allowed file extensions for uploads. ['.*'] means all extensions are allowed.
    """

    llms: dict[str, LLMConfig] = field(default_factory=dict)
    agents: dict[str, AgentConfig] = field(default_factory=dict)
    memories: dict[str, MemoryConfig] = field(default_factory=dict)
    default_agent: str = _DEFAULT_AGENT
    sandbox: SandboxConfig = field(default_factory=SandboxConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    runtime: str = 'eventstream'
    file_store: str = 'memory'
    file_store_path: str = '/tmp/file_store'
    # TODO: clean up workspace path after the removal of ServerRuntime
    workspace_base: str = os.path.join(os.getcwd(), 'workspace')
    workspace_mount_path: str | None = (
        UndefinedString.UNDEFINED  # this path should always be set when config is fully loaded
    )  # when set to None, do not mount the workspace
    workspace_mount_path_in_sandbox: str = '/workspace'
    workspace_mount_rewrite: str | None = None
    cache_dir: str = '/tmp/cache'
    run_as_openhands: bool = True
    max_iterations: int = _MAX_ITERATIONS
    max_budget_per_task: float | None = None
    e2b_api_key: str = ''
    disable_color: bool = False
    jwt_secret: str = uuid.uuid4().hex
    debug: bool = False
    enable_cli_session: bool = False
    file_uploads_max_file_size_mb: int = 0
    file_uploads_restrict_file_types: bool = False
    file_uploads_allowed_extensions: list[str] = field(default_factory=lambda: ['.*'])

    defaults_dict: ClassVar[dict] = {}

    def get_llm_config(self, name: str = 'llm') -> LLMConfig:
        """Get the LLM configuration for the specified name.

        Args:
            name: The name of the LLM configuration to retrieve. Defaults to 'llm'.

        Returns:
            The LLMConfig object for the specified name.

        Note:
            If the specified name is not found, it falls back to the default 'llm' config.
            If 'llm' config is not found, it creates a new default LLMConfig.
        """
        if name in self.llms:
            return self.llms[name]
        if name is not None and name != 'llm':
            logger.openhands_logger.warning(
                f'llm config group {name} not found, using default config'
            )
        if 'llm' not in self.llms:
            self.llms['llm'] = LLMConfig()
        return self.llms['llm']

    def set_llm_config(self, value: LLMConfig, name: str = 'llm') -> None:
        """Set the LLM configuration for the specified name.

        Args:
            value: The LLMConfig object to set.
            name: The name of the LLM configuration to set. Defaults to 'llm'.
        """
        self.llms[name] = value

    def get_agent_config(self, name: str = 'agent') -> AgentConfig:
        """Get the agent configuration for the specified name.

        Args:
            name: The name of the agent configuration to retrieve. Defaults to 'agent'.

        Returns:
            The AgentConfig object for the specified name.

        Note:
            If the specified name is not found, it falls back to the default 'agent' config.
            If 'agent' config is not found, it creates a new default AgentConfig.
        """
        if name in self.agents:
            return self.agents[name]
        if 'agent' not in self.agents:
            self.agents['agent'] = AgentConfig()
        return self.agents['agent']

    def set_agent_config(self, value: AgentConfig, name: str = 'agent') -> None:
        """Set the agent configuration for the specified name.

        Args:
            value: The AgentConfig object to set.
            name: The name of the agent configuration to set. Defaults to 'agent'.
        """
        self.agents[name] = value

    def get_memory_config(self, name: str = 'memory') -> MemoryConfig:
        """Get the memory configuration for the specified name.

        Args:
            name: The name of the memory configuration to retrieve. Defaults to 'memory'.

        Returns:
            The MemoryConfig object for the specified name.

        Note:
            If the specified name is not found, it falls back to the default 'memory' config.
            If 'memory' config is not found, it creates a new default MemoryConfig.
        """
        if name in self.memories:
            return self.memories[name]
        if name is not None and name != 'memory':
            logger.openhands_logger.warning(
                f'Memory config group {name} not found, using default config'
            )
        if 'memory' not in self.memories:
            self.memories['memory'] = MemoryConfig()
        return self.memories['memory']

    def set_memory_config(self, value: MemoryConfig, name: str = 'memory') -> None:
        """Set the memory configuration for the specified name.

        Args:
            value: The MemoryConfig object to set.
            name: The name of the memory configuration to set. Defaults to 'memory'.
        """
        self.memories[name] = value

    def get_memory_config_from_agent(self, name: str = 'agent') -> MemoryConfig:
        """Get the memory configuration associated with the specified agent.

        Args:
            name: The name of the agent configuration to use. Defaults to 'agent'.

        Returns:
            The MemoryConfig object associated with the specified agent.
        """
        agent_config: AgentConfig = self.get_agent_config(name)
        return agent_config.get_memory_config(self)

    def get_agent_to_llm_config_map(self) -> dict[str, LLMConfig]:
        """Get a map of agent names to their associated LLM configurations.

        Returns:
            A dictionary mapping agent names to their LLMConfig objects.
        """
        return {name: agent.get_llm_config(self) for name, agent in self.agents.items()}

    def get_llm_config_from_agent(self, name: str = 'agent') -> LLMConfig:
        """Get the LLM configuration associated with the specified agent.

        Args:
            name: The name of the agent configuration to use. Defaults to 'agent'.

        Returns:
            The LLMConfig object associated with the specified agent.
        """
        agent_config: AgentConfig = self.get_agent_config(name)
        return agent_config.get_llm_config(self)

    def get_agent_configs(self) -> dict[str, AgentConfig]:
        """Get all agent configurations.

        Returns:
            A dictionary of all agent configurations.
        """
        return self.agents

    def __post_init__(self) -> None:
        """Post-initialization hook, called when the instance is created with only default values."""
        AppConfig.defaults_dict = self.defaults_to_dict()

    @classmethod
    def load_from_env(cls, env_dict: dict[str, str]) -> 'AppConfig':
        """Reads the env-style vars and sets config attributes based on env vars or a config.toml dict.

        Args:
            env_dict: The environment variables.

        Note:
            This method is compatible with vars like LLM_BASE_URL, AGENT_MEMORY_ENABLED, SANDBOX_TIMEOUT and others.
        """
        config = cls()

        # Load main AppConfig fields
        for f in fields(cls):
            if f.name in ['llms', 'agents', 'memories', 'sandbox', 'security']:
                continue  # These are handled separately
            env_var_name = f.name.upper()
            if env_var_name in env_dict:
                value = env_dict[env_var_name]
                if value:
                    try:
                        setattr(config, f.name, cls._cast_value(f.type, value))
                    except ValueError as e:
                        logger.openhands_logger.warning(f'Error setting {f.name}: {e}')

        # Load sub-configs
        config.llms['llm'] = LLMConfig.load_from_env(env_dict)
        config.agents['agent'] = AgentConfig.load_from_env(env_dict)
        config.memories['memory'] = MemoryConfig.load_from_env(env_dict)
        config.sandbox = SandboxConfig.load_from_env(env_dict)
        config.security = SecurityConfig.load_from_env(env_dict)

        return config

    @classmethod
    def load_from_toml(cls, toml_config: dict | None) -> 'AppConfig':
        """Load configuration from a TOML dictionary.

        Args:
            toml_config: A dictionary containing TOML configuration.

        Returns:
            An AppConfig object with values loaded from the TOML configuration.
        """
        config = cls()

        if toml_config is None:
            return config

        # First, load the old-style config (env-style)
        if 'core' not in toml_config:
            config = cls.load_from_env(toml_config)

        # Then, load and override with the new-style config
        if 'core' in toml_config:
            for key, value in toml_config['core'].items():
                if hasattr(config, key):
                    try:
                        setattr(config, key, value)
                    except ValueError as e:
                        logger.openhands_logger.warning(f'Error setting {key}: {e}')
                else:
                    logger.openhands_logger.warning(
                        f'Unknown key in core config: "{key}"'
                    )

        # Load and override other configs
        config.llms.update(LLMConfig.load_from_toml(toml_config))
        print('Agents first: ', config.agents)
        config.agents.update(AgentConfig.load_from_toml(toml_config))
        print('Agents second: ', config.agents)
        config.memories.update(MemoryConfig.load_from_toml(toml_config))
        config.sandbox = SandboxConfig.load_from_toml(toml_config)
        config.security = SecurityConfig.load_from_toml(toml_config)

        # Log warnings for unknown keys
        for key in toml_config:
            if key not in ['core', 'llm', 'agent', 'memory', 'sandbox', 'security']:
                logger.openhands_logger.warning(f'Unknown key in config: "{key}"')

        return config

    def __str__(self) -> str:
        """Return a string representation of the AppConfig object."""
        attr_str = []
        for f in fields(self):
            attr_name = f.name
            attr_value = getattr(self, f.name)

            if attr_name in [
                'e2b_api_key',
                'github_token',
                'jwt_secret',
            ]:
                attr_value = '******' if attr_value else None

            attr_str.append(f'{attr_name}={repr(attr_value)}')

        return f"AppConfig({', '.join(attr_str)})"

    def __repr__(self) -> str:
        """Return a string representation of the AppConfig object."""
        return self.__str__()


def get_field_info(f: Any) -> dict[str, Any]:
    """Extract information about a dataclass field: type, optional, and default.

    Args:
        f: The field to extract information from.

    Returns:
        A dict with the field's type, whether it's optional, and its default value.
    """
    field_type = f.type
    optional = False

    # for types like str | None, find the non-None type and set optional to True
    # this is useful for the frontend to know if a field is optional
    # and to show the correct type in the UI
    # Note: this only works for UnionTypes with None as one of the types
    if get_origin(field_type) is UnionType:
        types = get_args(field_type)
        non_none_arg = next((t for t in types if t is not type(None)), None)
        if non_none_arg is not None:
            field_type = non_none_arg
            optional = True

    # type name in a pretty format
    type_name = (
        field_type.__name__ if hasattr(field_type, '__name__') else str(field_type)
    )

    # default is always present
    default = f.default

    # return a schema with the useful info for frontend
    return {'type': type_name.lower(), 'optional': optional, 'default': default}


def load_dict_from_toml(toml_file: str = 'config.toml') -> dict[str, Any] | None:
    """Load configuration from a TOML file.

    Args:
        toml_file: The path to the TOML configuration file. Defaults to 'config.toml'.

    Note:
        If the TOML file is not found or cannot be parsed, appropriate warnings will be logged.
    """
    try:
        with open(toml_file, 'r', encoding='utf-8') as toml_contents:
            toml_dict = toml.load(toml_contents)
    except FileNotFoundError:
        logger.openhands_logger.warning(f'Config file not found: {toml_file}')
        return None
    except toml.TomlDecodeError as e:
        logger.openhands_logger.warning(
            f'Cannot parse config from toml, toml values have not been applied.\nError: {e}',
            exc_info=False,
        )
        return None

    return toml_dict


def finalize_config(cfg: AppConfig) -> None:
    """Perform final tweaks to the configuration after it's been loaded.

    Args:
        cfg: The AppConfig object to finalize.

    Note:
        This function sets default values for certain configurations if they haven't been set,
        ensures directory existence, and performs compatibility checks.
    """
    if cfg.workspace_mount_path is UndefinedString.UNDEFINED:
        cfg.workspace_mount_path = os.path.abspath(cfg.workspace_base)
    cfg.workspace_base = os.path.abspath(cfg.workspace_base)

    if cfg.workspace_mount_rewrite:
        base = cfg.workspace_base or os.getcwd()
        parts = cfg.workspace_mount_rewrite.split(':')
        cfg.workspace_mount_path = base.replace(parts[0], parts[1])

    default_llm = cfg.get_llm_config()
    default_memory = cfg.get_memory_config()
    # Compatibility: If base_url is not set in memory config, use the one from LLM config
    if hasattr(default_llm, 'embedding_base_url'):
        default_memory.base_url = getattr(default_llm, 'embedding_base_url')
        logger.openhands_logger.warning(
            "Deprecated: 'embedding_base_url' should be set in memory config as base_url. "
            'Loaded from default LLM config.'
        )
    if hasattr(default_llm, 'embedding_model'):
        default_memory.embedding_model = getattr(default_llm, 'embedding_model')
        logger.openhands_logger.warning(
            "Deprecated: 'embedding_model' should be set in memory config. "
            'Loaded from default LLM config.'
        )
    if default_memory.embedding_deployment_name is None and hasattr(
        default_llm, 'embedding_deployment_name'
    ):
        default_memory.embedding_deployment_name = getattr(
            default_llm, 'embedding_deployment_name'
        )
        logger.openhands_logger.warning(
            "Deprecated: 'embedding_deployment_name' should be set in memory config. "
            'Loaded from default LLM config.'
        )

    if cfg.sandbox.use_host_network and platform.system() == 'Darwin':
        logger.openhands_logger.warning(
            'Please upgrade to Docker Desktop 4.29.0 or later to use host network mode on macOS. '
            'See https://github.com/docker/roadmap/issues/238#issuecomment-2044688144 for more information.'
        )

    # make sure cache dir exists
    if cfg.cache_dir:
        pathlib.Path(cfg.cache_dir).mkdir(parents=True, exist_ok=True)


# Utility function for command line --group argument
def get_llm_config_arg(
    llm_config_arg: str, toml_file: str = 'config.toml'
) -> LLMConfig | None:
    """Get a group of LLM settings from the config file.

    A group in config.toml can look like this:

    ```
    [llm.gpt-3.5-for-eval]
    model = 'gpt-3.5-turbo'
    api_key = '...'
    temperature = 0.5
    num_retries = 10
    ...
    ```

    The user-defined group name, like "gpt-3.5-for-eval", is the argument to this function. The function will load the LLMConfig object
    with the settings of this group, from the config file, and set it as the LLMConfig object for the app.

    Note that the group must be under "llm" group, or in other words, the group name must start with "llm.".

    Args:
        llm_config_arg: The group of LLM settings to get from the config.toml file.
        toml_file: The path to the TOML configuration file. Defaults to 'config.toml'.

    Returns:
        LLMConfig: The LLMConfig object with the settings from the config file, or None if not found or an error occurred.
    """
    # keep only the name, just in case
    llm_config_arg = llm_config_arg.strip('[]')

    # truncate the prefix, just in case
    if llm_config_arg.startswith('llm.'):
        llm_config_arg = llm_config_arg[4:]

    logger.openhands_logger.info(f'Loading llm config from {llm_config_arg}')

    # load the toml file
    try:
        with open(toml_file, 'r', encoding='utf-8') as toml_contents:
            toml_config = toml.load(toml_contents)
    except FileNotFoundError as e:
        logger.openhands_logger.error(f'Config file not found: {e}')
        return None
    except toml.TomlDecodeError as e:
        logger.openhands_logger.error(
            f'Cannot parse llm group from {llm_config_arg}. Exception: {e}'
        )
        return None

    # update the llm config with the specified section
    if 'llm' in toml_config and llm_config_arg in toml_config['llm']:
        return LLMConfig(**toml_config['llm'][llm_config_arg])
    logger.openhands_logger.debug(f'Loading from toml failed for {llm_config_arg}')
    return None


# Command line arguments
def get_parser() -> argparse.ArgumentParser:
    """Get the parser for the command line arguments."""
    parser = argparse.ArgumentParser(description='Run an agent with a specific task')
    parser.add_argument(
        '-d',
        '--directory',
        type=str,
        help='The working directory for the agent',
    )
    parser.add_argument(
        '-t',
        '--task',
        type=str,
        default='',
        help='The task for the agent to perform',
    )
    parser.add_argument(
        '-f',
        '--file',
        type=str,
        help='Path to a file containing the task. Overrides -t if both are provided.',
    )
    parser.add_argument(
        '-c',
        '--agent-cls',
        default=_DEFAULT_AGENT,
        type=str,
        help='Name of the default agent to use',
    )
    parser.add_argument(
        '-i',
        '--max-iterations',
        default=_MAX_ITERATIONS,
        type=int,
        help='The maximum number of iterations to run the agent',
    )
    parser.add_argument(
        '-b',
        '--max-budget-per-task',
        type=float,
        help='The maximum budget allowed per task, beyond which the agent will stop.',
    )
    # --eval configs are for evaluations only
    parser.add_argument(
        '--eval-output-dir',
        default='evaluation/evaluation_outputs/outputs',
        type=str,
        help='The directory to save evaluation output',
    )
    parser.add_argument(
        '--eval-n-limit',
        default=None,
        type=int,
        help='The number of instances to evaluate',
    )
    parser.add_argument(
        '--eval-num-workers',
        default=4,
        type=int,
        help='The number of workers to use for evaluation',
    )
    parser.add_argument(
        '--eval-note',
        default=None,
        type=str,
        help='The note to add to the evaluation directory',
    )
    parser.add_argument(
        '-l',
        '--llm-config',
        default=None,
        type=str,
        help='Replace default LLM ([llm] section in config.toml) config with the specified LLM config, e.g. "llama3" for [llm.llama3] section in config.toml',
    )
    parser.add_argument(
        '-n',
        '--name',
        default='default',
        type=str,
        help='Name for the session',
    )
    return parser


def parse_arguments() -> argparse.Namespace:
    """Parse the command line arguments."""
    parser = get_parser()
    parsed_args, _ = parser.parse_known_args()
    return parsed_args


def load_app_config(set_logging_levels: bool = True) -> AppConfig:
    """Load the configuration from the config.toml file and environment variables.

    Args:
        set_logging_levels: Whether to set the global variables for logging levels.

    Returns:
        An AppConfig object with the loaded configuration.

    Note:
        The configuration is loaded in the following order of precedence:
        1. Environment variables
        2. TOML configuration file
        3. Default values initialized in the dataclasses
    """
    config = AppConfig()
    toml_dict = load_dict_from_toml()
    if toml_dict:
        AppConfig.load_from_toml(toml_dict)
    env_dict = dict(os.environ)
    AppConfig.load_from_env(env_dict)
    finalize_config(config)
    if set_logging_levels:
        logger.DEBUG = config.debug
        logger.DISABLE_COLOR_PRINTING = config.disable_color
    return config