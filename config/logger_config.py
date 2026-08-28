import logging.config
import sys
from pathlib import Path

import yaml


def _in_airflow() -> bool:
    """Vrai si on s'exécute dans un processus Airflow (scheduler, worker, ...).

    Dans ce cas, c'est Airflow qui possède la configuration de logging : un
    ``logging.config.dictConfig`` ici écraserait ses handlers, et un handler
    console écrivant sur ``stderr`` serait capturé par Airflow puis re-loggué
    en ERROR (les lignes INFO apparaîtraient comme des erreurs).
    """
    return "airflow" in sys.modules


def setup_logging(name: str, config_path: str = "logging.yml", log_dir: str = "logs"):
    """Configure et renvoie un logger.

    Sous Airflow, ne reconfigure rien et renvoie un logger qui propage vers
    les handlers d'Airflow (les niveaux INFO/WARN/ERROR sont conservés tels
    quels dans les logs de tâche).

    Sinon, charge ``logging.yml`` s'il existe (RotatingFileHandler vers
    ``logs/app.log`` + StreamHandler), ou applique une configuration de base
    équivalente.

    Args:
        name (str): Nom du logger (généralement ``__name__``).
        config_path (str, optional): Nom du fichier YAML dans ``config/``.
        log_dir (str, optional): Dossier de destination des fichiers de log.

    Returns:
        logging.Logger: Logger configuré.
    """
    if _in_airflow():
        return logging.getLogger(name)

    CONFIG_DIR = Path(__file__).resolve().parent
    APP_ROOT = CONFIG_DIR.parent
    LOG_DIR = APP_ROOT / log_dir
    CONFIG_FILE = CONFIG_DIR / config_path

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file_path = LOG_DIR / "app.log"

    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f.read())
            # Chemin du fichier de log mis à jour dynamiquement pour être absolu
            if "handlers" in config and "file" in config["handlers"]:
                config["handlers"]["file"]["filename"] = str(log_file_path)
            logging.config.dictConfig(config)
    else:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
            handlers=[
                logging.FileHandler(log_file_path, encoding="utf-8"),
                logging.StreamHandler(),
            ],
        )

    return logging.getLogger(name)
