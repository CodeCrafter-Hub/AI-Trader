import os
import asyncio
from datetime import datetime, timedelta
import json
from pathlib import Path
from typing import Dict, List
from dotenv import load_dotenv
load_dotenv()

# Import tools and prompts
from tools.general_tools import get_config_value, write_config_value
from prompts.agent_prompt import all_nasdaq_100_symbols


# Agent class mapping table - for dynamic import and instantiation
AGENT_REGISTRY = {
    "BaseAgent": {
        "module": "agent.base_agent.base_agent",
        "class": "BaseAgent"
    },
}


def _validate_date(date_str: str, field_name: str, errors: List[str]) -> None:
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        errors.append(f"{field_name} must be in YYYY-MM-DD format (received {date_str})")


def _validate_agent_config(config: Dict, errors: List[str]) -> None:
    if not isinstance(config, dict):
        errors.append("agent_config must be an object")
        return

    numeric_fields = [
        ("max_steps", 1),
        ("max_retries", 1),
        ("base_delay", 0),
        ("initial_cash", 0),
    ]
    for field, min_value in numeric_fields:
        value = config.get(field)
        if value is None:
            errors.append(f"agent_config missing required field '{field}'")
            continue
        if not isinstance(value, (int, float)) or value < min_value:
            errors.append(f"agent_config field '{field}' must be >= {min_value} (received {value})")


def _validate_models(models: List[Dict], errors: List[str]) -> None:
    if not isinstance(models, list) or not models:
        errors.append("models must be a non-empty list")
        return

    seen_signatures = set()
    for idx, model in enumerate(models):
        prefix = f"models[{idx}]"
        if not isinstance(model, dict):
            errors.append(f"{prefix} must be an object")
            continue
        signature = model.get("signature")
        basemodel = model.get("basemodel")
        if not signature:
            errors.append(f"{prefix} is missing 'signature'")
        elif signature in seen_signatures:
            errors.append(f"Duplicate model signature detected: {signature}")
        else:
            seen_signatures.add(signature)
        if not basemodel:
            errors.append(f"{prefix} is missing 'basemodel'")

        overrides = model.get("agent_overrides", {})
        if overrides and not isinstance(overrides, dict):
            errors.append(f"{prefix}.agent_overrides must be an object when provided")


def validate_config(config: Dict) -> None:
    errors: List[str] = []

    if not isinstance(config, dict):
        raise ValueError("Configuration must be a JSON object")

    date_range = config.get("date_range", {})
    init_date_obj = end_date_obj = None
    if not isinstance(date_range, dict):
        errors.append("date_range must be an object")
    else:
        init_date = date_range.get("init_date", "")
        end_date = date_range.get("end_date", "")
        _validate_date(init_date, "date_range.init_date", errors)
        _validate_date(end_date, "date_range.end_date", errors)
        try:
            init_date_obj = datetime.strptime(init_date, "%Y-%m-%d").date()
            end_date_obj = datetime.strptime(end_date, "%Y-%m-%d").date()
            if init_date_obj > end_date_obj:
                errors.append("date_range.init_date must be on or before date_range.end_date")
        except ValueError:
            pass

    _validate_agent_config(config.get("agent_config", {}), errors)

    log_config = config.get("log_config", {})
    if not isinstance(log_config, dict):
        errors.append("log_config must be an object")
    elif not isinstance(log_config.get("log_path", ""), str):
        errors.append("log_config.log_path must be a string")

    _validate_models(config.get("models", []), errors)

    enabled_models = [m for m in config.get("models", []) if isinstance(m, dict) and m.get("enabled", True)]
    if not enabled_models:
        errors.append("At least one model must be enabled")

    agent_type = config.get("agent_type")
    if not agent_type:
        errors.append("agent_type is required")
    elif agent_type not in AGENT_REGISTRY:
        errors.append(f"Unsupported agent_type '{agent_type}'. Supported types: {', '.join(AGENT_REGISTRY)}")

    if errors:
        raise ValueError("\n - " + "\n - ".join(errors))


def _merge_agent_config(base: Dict, overrides: Dict) -> Dict:
    merged = {**base}
    merged.update({k: v for k, v in overrides.items() if v is not None})
    return merged


def get_agent_class(agent_type):
    """
    Dynamically import and return the corresponding class based on agent type name
    
    Args:
        agent_type: Agent type name (e.g., "BaseAgent")
        
    Returns:
        Agent class
        
    Raises:
        ValueError: If agent type is not supported
        ImportError: If unable to import agent module
    """
    if agent_type not in AGENT_REGISTRY:
        supported_types = ", ".join(AGENT_REGISTRY.keys())
        raise ValueError(
            f"❌ Unsupported agent type: {agent_type}\n"
            f"   Supported types: {supported_types}"
        )
    
    agent_info = AGENT_REGISTRY[agent_type]
    module_path = agent_info["module"]
    class_name = agent_info["class"]
    
    try:
        # Dynamic import module
        import importlib
        module = importlib.import_module(module_path)
        agent_class = getattr(module, class_name)
        print(f"✅ Successfully loaded Agent class: {agent_type} (from {module_path})")
        return agent_class
    except ImportError as e:
        raise ImportError(f"❌ Unable to import agent module {module_path}: {e}")
    except AttributeError as e:
        raise AttributeError(f"❌ Class {class_name} not found in module {module_path}: {e}")


def load_config(config_path=None):
    """
    Load configuration file from configs directory
    
    Args:
        config_path: Configuration file path, if None use default config
        
    Returns:
        dict: Configuration dictionary
    """
    if config_path is None:
        # Default configuration file path
        config_path = Path(__file__).parent / "configs" / "default_config.json"
    else:
        config_path = Path(config_path)
    
    if not config_path.exists():
        print(f"❌ Configuration file does not exist: {config_path}")
        exit(1)
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        print(f"✅ Successfully loaded configuration file: {config_path}")
        return config
    except json.JSONDecodeError as e:
        print(f"❌ Configuration file JSON format error: {e}")
        exit(1)
    except Exception as e:
        print(f"❌ Failed to load configuration file: {e}")
        exit(1)


async def main(config_path=None):
    """Run trading experiment using BaseAgent class

    Args:
        config_path: Configuration file path, if None use default config
    """
    # Load configuration file
    config = load_config(config_path)

    try:
        validate_config(config)
    except ValueError as e:
        print(f"❌ Configuration validation failed:\n{e}")
        exit(1)

    # Get Agent type
    agent_type = config.get("agent_type", "BaseAgent")
    try:
        AgentClass = get_agent_class(agent_type)
    except (ValueError, ImportError, AttributeError) as e:
        print(str(e))
        exit(1)
    
    # Get date range from configuration file
    INIT_DATE = config["date_range"]["init_date"]
    END_DATE = config["date_range"]["end_date"]
    
    # Environment variables can override dates in configuration file
    if os.getenv("INIT_DATE"):
        INIT_DATE = os.getenv("INIT_DATE")
        print(f"⚠️  Using environment variable to override INIT_DATE: {INIT_DATE}")
    if os.getenv("END_DATE"):
        END_DATE = os.getenv("END_DATE")
        print(f"⚠️  Using environment variable to override END_DATE: {END_DATE}")

    # Validate date range
    try:
        INIT_DATE_obj = datetime.strptime(INIT_DATE, "%Y-%m-%d").date()
        END_DATE_obj = datetime.strptime(END_DATE, "%Y-%m-%d").date()
    except ValueError as e:
        print(f"❌ Invalid date value: {e}")
        exit(1)
    if INIT_DATE_obj > END_DATE_obj:
        print("❌ INIT_DATE is greater than END_DATE")
        exit(1)
 
    # Get model list from configuration file (only select enabled models)
    enabled_models = [
        model for model in config["models"]
        if model.get("enabled", True)
    ]

    if not enabled_models:
        print("❌ No enabled models found in configuration")
        exit(1)

    # Get agent configuration
    agent_config = config.get("agent_config", {})
    log_config = config.get("log_config", {})

    # Display enabled model information
    model_names = [m.get("name", m.get("signature")) for m in enabled_models]

    print("🚀 Starting trading experiment")
    print(f"🤖 Agent type: {agent_type}")
    print(f"📅 Date range: {INIT_DATE} to {END_DATE}")
    print(f"🤖 Model list: {model_names}")
    print(
        "⚙️  Base agent config: max_steps={max_steps}, max_retries={max_retries}, base_delay={base_delay}, initial_cash={initial_cash}".format(
            max_steps=agent_config.get("max_steps"),
            max_retries=agent_config.get("max_retries"),
            base_delay=agent_config.get("base_delay"),
            initial_cash=agent_config.get("initial_cash"),
        )
    )
                    
    for model_config in enabled_models:
        # Read basemodel and signature directly from configuration file
        model_name = model_config.get("name", "unknown")
        basemodel = model_config.get("basemodel")
        signature = model_config.get("signature")
        openai_base_url = model_config.get("openai_base_url", None)
        openai_api_key = model_config.get("openai_api_key", None)
        merged_agent_config = _merge_agent_config(agent_config, model_config.get("agent_overrides", {}))
        validation_errors: List[str] = []
        _validate_agent_config(merged_agent_config, validation_errors)
        if validation_errors:
            print(f"❌ Invalid agent_overrides for {model_name}: {'; '.join(validation_errors)}")
            continue
        max_steps = merged_agent_config.get("max_steps", 10)
        max_retries = merged_agent_config.get("max_retries", 3)
        base_delay = merged_agent_config.get("base_delay", 0.5)
        initial_cash = merged_agent_config.get("initial_cash", 10000.0)

        # Validate required fields
        if not basemodel:
            print(f"❌ Model {model_name} missing basemodel field")
            continue
        if not signature:
            print(f"❌ Model {model_name} missing signature field")
            continue
        
        print("=" * 60)
        print(f"🤖 Processing model: {model_name}")
        print(f"📝 Signature: {signature}")
        print(f"🔧 BaseModel: {basemodel}")
        if model_config.get("agent_overrides"):
            print(f"⚙️  Overrides: {model_config.get('agent_overrides')}")
        
        # Initialize runtime configuration
        write_config_value("SIGNATURE", signature)
        write_config_value("TODAY_DATE", END_DATE)
        write_config_value("IF_TRADE", False)


        # Get log path configuration
        log_path = log_config.get("log_path", "./data/agent_data")

        try:
            # Dynamically create Agent instance
            agent = AgentClass(
                signature=signature,
                basemodel=basemodel,
                stock_symbols=all_nasdaq_100_symbols,
                log_path=log_path,
                openai_base_url=openai_base_url,
                openai_api_key=openai_api_key,
                max_steps=max_steps,
                max_retries=max_retries,
                base_delay=base_delay,
                initial_cash=initial_cash,
                init_date=INIT_DATE
            )
            
            print(f"✅ {agent_type} instance created successfully: {agent}")
            
            # Initialize MCP connection and AI model
            await agent.initialize()
            print("✅ Initialization successful")
            # Run all trading days in date range
            await agent.run_date_range(INIT_DATE, END_DATE)

            # Display final position summary
            summary = agent.get_position_summary()
            print(f"📊 Final position summary:")
            print(f"   - Latest date: {summary.get('latest_date')}")
            print(f"   - Total records: {summary.get('total_records')}")
            print(f"   - Cash balance: ${summary.get('positions', {}).get('CASH', 0):.2f}")

            performance_report = agent.get_performance_report()
            if performance_report:
                metrics = performance_report["metrics"]
                print("📈 Performance metrics:")
                print(f"   - Cumulative return: {metrics.get('cumulative_return', 0):.2%}")
                print(f"   - Annualized return: {metrics.get('annualized_return', 0):.2%}")
                print(f"   - Max drawdown: {metrics.get('max_drawdown', 0):.2%}")
                print(f"   - Volatility: {metrics.get('volatility', 0):.2%}")
                print(f"   - Sharpe ratio: {metrics.get('sharpe_ratio', 0):.2f}")
                print(f"   - Sortino ratio: {metrics.get('sortino_ratio', 0):.2f}")
                print(f"   - Turnover: {metrics.get('turnover', 0):.2%}")
                if performance_report.get("missing_price_days"):
                    print(f"   - Missing price data on: {performance_report['missing_price_days']}")
                if performance_report.get("missing_price_symbols"):
                    print(f"   - Missing price files for: {performance_report['missing_price_symbols']}")
                skipped = performance_report.get("skipped_records", 0)
                if skipped:
                    print(f"   - Skipped malformed position entries: {skipped}")

        except Exception as e:
            print(f"❌ Error processing model {model_name} ({signature}): {str(e)}")
            print(f"📋 Error details: {e}")
            # Can choose to continue processing next model, or exit
            # continue  # Continue processing next model
            exit()  # Or exit program
        
        print("=" * 60)
        print(f"✅ Model {model_name} ({signature}) processing completed")
        print("=" * 60)
    
    print("🎉 All models processing completed!")
    
if __name__ == "__main__":
    import sys
    
    # Support specifying configuration file through command line arguments
    # Usage: python livebaseagent_config.py [config_path]
    # Example: python livebaseagent_config.py configs/my_config.json
    config_path = sys.argv[1] if len(sys.argv) > 1 else None
    
    if config_path:
        print(f"📄 Using specified configuration file: {config_path}")
    else:
        print(f"📄 Using default configuration file: configs/default_config.json")
    
    asyncio.run(main(config_path))

