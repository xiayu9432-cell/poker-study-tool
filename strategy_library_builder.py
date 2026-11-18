import argparse
import gzip
import hashlib
import itertools
import json
import math
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from table_info_parser import rake_strategy_policies


FORMAT_VERSION = 1


class ToolUnavailableError(RuntimeError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_value(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def write_gzip_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    payload = canonical_json(value).encode("utf-8")
    with temporary.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as target:
            target.write(payload)
    os.replace(temporary, path)


def read_gzip_json(path):
    with gzip.open(path, "rt", encoding="utf-8") as source:
        return json.load(source)


def safe_name(value):
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value)).strip("-") or "unknown"


def load_config(path):
    path = Path(path).resolve()
    config = json.loads(path.read_text(encoding="utf-8"))
    config["_path"] = str(path)
    root = Path(config.get("library_root", "strategy_library_data"))
    if not root.is_absolute():
        root = path.parent / root
    config["_root"] = str(root.resolve())
    return config


def build_scene_key(config, position, stack, pot, board, rake=None):
    solver = config["solver"]
    action = {
        "prior_chain": pot["prior_chain"],
        "raise_round": pot["raise_round"],
        "pot_type": pot["id"],
        "actor": position["actor"],
        "facing": position["facing"],
        "sizing_bucket": pot["sizing_bucket"],
    }
    for field in ("pot_bb", "hero_contributed_bb", "opponent_contributed_bb",
                  "current_price_bb", "call_amount_bb"):
        if field in pot:
            action[field] = pot[field]
    return {
        "schema_version": config["key_schema_version"],
        "game": {
            "variant": config["game"]["variant"],
            "betting": config["game"]["betting"],
            "players": pot.get("players", config["game"]["players"]),
        },
        "forced_bets": pot.get("forced_bets", config["game"]["forced_bets"]),
        "positions": position,
        "effective_stack": stack,
        "action": action,
        "board": {
            "street": board["street"],
            "class": board["class"],
            "representative": board["representative"],
            "blocker_model": board["blocker_model"],
        },
        "rake": pot.get("rake", rake if rake is not None else config["game"]["rake"]),
        "legal_actions": pot.get(
            "legal_actions", config["scenario_generator"].get("legal_actions", [])),
        "versions": {
            "solver": f'{solver["name"]}:{solver["version"]}',
            "ranges": config["range_version"],
            "library_schema": config["library_schema_version"],
        },
    }


def validate_scene_key(scene, config):
    required = {
        "schema_version", "game", "forced_bets", "positions", "effective_stack",
        "action", "board", "rake", "legal_actions", "versions",
    }
    missing = sorted(required - set(scene))
    if missing:
        raise ValueError("场景键缺少字段: " + ",".join(missing))
    if scene["schema_version"] != config["key_schema_version"]:
        raise ValueError("场景键结构版本不兼容")
    actions = scene["legal_actions"]
    if not isinstance(actions, list) or not actions:
        raise ValueError("合法动作集合为空")
    action_ids = [item.get("id") for item in actions]
    if None in action_ids or len(action_ids) != len(set(action_ids)):
        raise ValueError("合法动作标识缺失或重复")
    street = scene.get("board", {}).get("street")
    rake = scene.get("rake", {})
    rate, cap = rake.get("percent"), rake.get("cap_bb")
    if (isinstance(rate, bool) or not isinstance(rate, (int, float)) or
            isinstance(cap, bool) or not isinstance(cap, (int, float)) or
            not math.isfinite(rate) or not math.isfinite(cap) or rate < 0 or cap < 0):
        raise ValueError("场景抽成参数无效")
    if street == "preflop":
        if abs(rate) > 1e-12 or abs(cap) > 1e-9:
            raise ValueError("翻牌前策略库必须使用零抽成")
    elif street in ("flop", "turn", "river"):
        policies = rake_strategy_policies()
        if (rake.get("no_flop_no_drop") is not True or not any(
                abs(rate - item["percent"]) <= 1e-12 and
                abs(cap - item["cap_bb"]) <= 1e-9 for item in policies)):
            raise ValueError("翻牌后抽成不匹配平台标准政策")
    else:
        raise ValueError("未知街道禁止进入策略库")
    if (scene.get("board", {}).get("street") == "preflop" and
            scene.get("schema_version") == "scene-key-v2"):
        action = scene["action"]
        fields = ("pot_bb", "hero_contributed_bb", "opponent_contributed_bb",
                  "current_price_bb", "call_amount_bb")
        if any(not isinstance(action.get(field), (int, float)) for field in fields):
            raise ValueError("翻牌前场景缺少明确资金状态")
        pot_bb = float(action["pot_bb"])
        hero = float(action["hero_contributed_bb"])
        opponent = float(action["opponent_contributed_bb"])
        current = float(action["current_price_bb"])
        call = float(action["call_amount_bb"])
        if min(pot_bb, hero, opponent, current, call) < 0:
            raise ValueError("翻牌前资金状态不能为负数")
        if pot_bb + 1e-9 < hero + opponent:
            raise ValueError("底池小于双方已投入")
        if current + 1e-9 < max(hero, opponent):
            raise ValueError("当前最高投入小于已投入")
        if abs(call - max(0.0, current - hero)) > 1e-6:
            raise ValueError("跟注价与当前最高投入不一致")
    return scene


def shard_key(scene):
    return "__".join(safe_name(value) for value in (
        scene["game"]["variant"],
        f'{scene["game"]["players"]}p',
        scene["board"]["street"],
        scene["effective_stack"]["id"],
        scene["action"]["pot_type"],
    ))


def generated_scenes(config):
    generator = config["scenario_generator"]
    if generator.get("rake_policies_source") == "table_info_parser.rake_strategy_policies":
        from table_info_parser import rake_strategy_policies
        configured_rake_policies = rake_strategy_policies()
    else:
        configured_rake_policies = generator.get("rake_policies")
    declared = [item for item in generator.get("scenes", []) if item.get("enabled", True)]
    pairs = ((item["position"], item["pot"]) for item in declared) if declared else itertools.product(
        generator["positions"], generator["pot_types"])
    for position, pot in pairs:
        rake_policies = [pot["rake"]] if "rake" in pot else configured_rake_policies or [None]
        for stack, board, rake in itertools.product(
                generator["stack_buckets"], generator["board_classes"], rake_policies):
            allowed_stacks = pot.get("stack_bucket_ids")
            if allowed_stacks and stack.get("id") not in allowed_stacks:
                continue
            yield build_scene_key(config, position, stack, pot, board, rake), {
                "frequency": board.get("frequency", 1.0),
                "decision_value": pot.get("decision_value", 1.0),
                "uncertainty": board.get("uncertainty", 1.0),
                "compute_cost": board.get("compute_cost", 1.0),
            }


def validate_result(result, scene, config, require_verification=True):
    errors = []
    if result.get("format_version") != FORMAT_VERSION:
        errors.append("产物格式版本错误")
    if result.get("artifact_kind") != "equilibrium_strategy":
        errors.append("产物不是均衡策略")
    if result.get("formal") is not True or result.get("demo") is True:
        errors.append("演示或非正式产物禁止进入候选库")
    if result.get("scene_hash") != sha256_value(scene) or result.get("scene_key") != scene:
        errors.append("场景键或哈希不一致")
    solver = result.get("solver", {})
    if solver.get("kind") != "equilibrium_solver":
        errors.append("结果来源不是均衡求解器")
    if solver.get("name") != config["solver"]["name"] or solver.get("version") != config["solver"]["version"]:
        errors.append("求解器版本不一致")
    iterations = solver.get("iterations")
    exploitability = solver.get("exploitability_bb")
    if not isinstance(iterations, int) or iterations <= 0:
        errors.append("迭代次数无效")
    if not isinstance(exploitability, (int, float)) or not math.isfinite(exploitability):
        errors.append("缺少可被剥削度")
    elif exploitability > config["acceptance"]["max_exploitability_bb"]:
        errors.append("可被剥削度超过门槛")

    nodes = result.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        errors.append("没有策略节点")
        nodes = []
    seen_nodes = set()
    root_legal = {item["id"]: item for item in scene["legal_actions"]}
    probability_tolerance = config["acceptance"]["probability_tolerance"]
    for node in nodes:
        node_id = node.get("node_id")
        if not node_id or node_id in seen_nodes:
            errors.append("节点标识缺失或重复")
            continue
        seen_nodes.add(node_id)
        legal = node.get("legal_actions")
        if not isinstance(legal, list) or not legal:
            errors.append(f"节点 {node_id} 合法动作为空")
            continue
        legal_ids = []
        for action in legal:
            action_id = action.get("id")
            kind = action.get("kind")
            if not action_id or action_id in legal_ids:
                errors.append(f"节点 {node_id} 动作标识缺失或重复")
            legal_ids.append(action_id)
            if kind not in ("fold", "check", "call", "bet", "raise"):
                errors.append(f"节点 {node_id} 动作类型不合法")
            if kind in ("bet", "raise"):
                amount = action.get("amount", {})
                value = amount.get("value")
                if amount.get("unit") not in ("bb", "pot") or not isinstance(value, (int, float)) or value <= 0:
                    errors.append(f"节点 {node_id} 下注金额不合法")
        if node_id == "root" and {item["id"]: item for item in legal} != root_legal:
            errors.append("根节点合法动作与场景合同不一致")
        strategies = node.get("strategies")
        if not isinstance(strategies, list) or not strategies:
            errors.append(f"节点 {node_id} 没有手牌策略")
            continue
        seen_hands = set()
        for strategy in strategies:
            hand = strategy.get("hand")
            frequencies = strategy.get("actions")
            if not hand or hand in seen_hands:
                errors.append(f"节点 {node_id} 手牌键缺失或重复")
                continue
            seen_hands.add(hand)
            if not isinstance(frequencies, dict) or not frequencies:
                errors.append(f"节点 {node_id}/{hand} 频率为空")
                continue
            if not set(frequencies).issubset(set(legal_ids)):
                errors.append(f"节点 {node_id}/{hand} 含非法动作")
            values = list(frequencies.values())
            if any(not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 for value in values):
                errors.append(f"节点 {node_id}/{hand} 频率无效")
            elif abs(sum(values) - 1.0) > probability_tolerance:
                errors.append(f"节点 {node_id}/{hand} 概率和不为1")
            ev = strategy.get("ev", {})
            if ev and (not isinstance(ev, dict) or any(
                    not isinstance(value, (int, float)) or not math.isfinite(value) for value in ev.values())):
                errors.append(f"节点 {node_id}/{hand} EV无效")
            elif ev and not set(ev).issubset(set(legal_ids)):
                errors.append(f"节点 {node_id}/{hand} EV含非法动作")

    if require_verification:
        verification = result.get("verification", {})
        cross = verification.get("cross_validation", {})
        regression = verification.get("fixed_regression", {})
        if cross.get("passed") is not True or not cross.get("method"):
            errors.append("缺少独立交叉验证")
        cross_delta = cross.get("max_delta_bb")
        if not isinstance(cross_delta, (int, float)) or cross_delta < 0:
            errors.append("交叉验证差异无效")
        elif cross_delta > config["acceptance"]["max_cross_validation_delta_bb"]:
            errors.append("交叉验证差异超过门槛")
        if regression.get("passed") is not True or not isinstance(regression.get("cases"), int) or regression["cases"] <= 0:
            errors.append("缺少固定回归验证")
    return errors


def verification_execution_config(settings):
    payload = {"kind": settings.get("kind"), "command": settings.get("command")}
    if "solver" in settings:
        payload["solver"] = settings["solver"]
    if "evaluator" in settings:
        payload["evaluator"] = settings["evaluator"]
    return payload


def independent_verification_errors(result, config):
    settings = config.get("verification", {}).get("cross_validation", {})
    report = result.get("verification", {}).get("cross_validation", {})
    errors = []
    kind = settings.get("kind")
    if kind == "independent_equilibrium_solver":
        identity_key = "solver"
        expected_kind = "equilibrium_solver"
    elif kind == "independent_strategy_evaluator":
        identity_key = "evaluator"
        expected_kind = "independent_strategy_evaluator"
    elif kind == "independent_model_cross_check":
        identity_key = "evaluator"
        expected_kind = "independent_model_cross_check"
    else:
        return ["交叉验证器未配置为合格的独立验证器"]
    if report.get("passed") is not True:
        errors.append("独立验证未通过")
    configured = settings.get(identity_key, {})
    reported = report.get(identity_key, {})
    for field in ("name", "version"):
        if not configured.get(field):
            errors.append(f"独立验证器缺少{field}")
        elif reported.get(field) != configured[field]:
            errors.append(f"独立验证器报告{field}与配置不一致")
    if reported.get("kind") != expected_kind:
        errors.append("独立验证报告身份类型错误")
    if kind == "independent_equilibrium_solver":
        primary = config.get("solver", {})
        if configured.get("name") == primary.get("name") and configured.get("version") == primary.get("version"):
            errors.append("独立求解器与主求解器身份相同")
    elif kind == "independent_strategy_evaluator":
        samples = report.get("samples")
        metrics = report.get("independent_metrics", {})
        exploitability = report.get("independent_exploitability_bb")
        if not isinstance(samples, int) or samples <= 0:
            errors.append("独立策略评估缺少有效样本数")
        if any(not isinstance(metrics.get(field), (int, float)) or not math.isfinite(metrics[field])
               for field in ("base_value_bb", "hero_best_response_bb",
                             "villain_best_response_bb", "exploitability_bb")):
            errors.append("独立策略评估指标不完整")
        if not isinstance(exploitability, (int, float)) or not math.isfinite(exploitability):
            errors.append("独立策略评估缺少可被剥削度")
        elif exploitability > config["acceptance"]["max_exploitability_bb"]:
            errors.append("独立策略评估可被剥削度超过门槛")
    else:
        cases = report.get("cases")
        samples = report.get("samples")
        if not isinstance(cases, int) or cases <= 0 or samples != cases:
            errors.append("独立模型交叉验证缺少有效案例数")
        for field, setting in (
                ("t2_t3_action_agreement_rate", "min_t2_t3_action_agreement_rate"),
                ("candidate_direction_agreement_rate", "min_candidate_direction_agreement_rate")):
            value = report.get(field)
            minimum = settings.get(setting)
            if (not isinstance(value, (int, float)) or not math.isfinite(value) or
                    value < 0 or value > 1):
                errors.append(f"独立模型交叉验证{field}无效")
            elif (not isinstance(minimum, (int, float)) or minimum < 0 or minimum > 1 or
                  value < minimum):
                errors.append(f"独立模型交叉验证{field}未达到门槛")
        for field in ("probability_checks_passed", "action_mapping_checks_passed", "rake_checks_passed"):
            if report.get(field) is not True:
                errors.append(f"独立模型交叉验证{field}未通过")
        if report.get("exploitability_evaluated") is not False:
            errors.append("独立模型交叉验证不得声称已评估可被剥削度")
        forbidden = ("independent_exploitability_bb", "exploitability_bb", "independent_metrics")
        if any(field in report for field in forbidden):
            errors.append("独立模型交叉验证含伪造或不适用的可被剥削度字段")
    if report.get("independent") is not True:
        errors.append("独立验证报告未声明独立执行")
    delta = report.get("max_delta_bb")
    if not isinstance(delta, (int, float)) or not math.isfinite(delta) or delta < 0:
        errors.append("独立验证差异无效")
    elif delta > config["acceptance"]["max_cross_validation_delta_bb"]:
        errors.append("独立验证差异超过门槛")
    execution = report.get("builder_execution", {})
    expected_hash = sha256_value(verification_execution_config(settings))
    if execution.get("executed") is not True or execution.get("config_hash") != expected_hash:
        errors.append("独立验证没有建库器执行凭据")
    return errors


def independent_solver_verification_errors(result, config):
    return independent_verification_errors(result, config)


class CommandAdapter:
    def __init__(self, settings, base_dir, label):
        self.settings = settings
        self.base_dir = Path(base_dir)
        self.label = label

    def _executable(self):
        configured = self.settings.get("executable")
        if configured:
            path = Path(configured)
            if not path.is_absolute():
                path = self.base_dir / path
            return str(path) if path.exists() else None
        for name in self.settings.get("discover", []):
            found = shutil.which(name)
            if found:
                return found
        return None

    def command(self, values):
        template = self.settings.get("command")
        if not isinstance(template, list) or not template:
            raise ToolUnavailableError(f"{self.label}调用模板未配置")
        executable = self._executable()
        if any("{executable}" in part for part in template) and not executable:
            raise ToolUnavailableError(f"{self.label}可执行文件不可用")
        values = {**values, "executable": executable or "", "python": sys.executable}
        command = [str(part).format(**values) for part in template]
        program = command[0]
        if not (Path(program).exists() or shutil.which(program)):
            raise ToolUnavailableError(f"{self.label}命令不可执行")
        return command

    def run(self, values, log_path):
        command = self.command(values)
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        with Path(log_path).open("ab") as log:
            completed = subprocess.run(
                command, cwd=self.base_dir, stdout=log, stderr=subprocess.STDOUT,
                timeout=int(self.settings.get("timeout_seconds", 86400)), check=False,
            )
        if completed.returncode:
            raise RuntimeError(f"{self.label}退出码 {completed.returncode}")


class StrategyLibraryBuilder:
    def __init__(self, config):
        self.config = config
        self.root = Path(config["_root"])
        self.candidate = self.root / "candidate"
        self.work = self.root / "work"
        self.releases = self.root / "releases"
        self.db_path = self.candidate / "index.sqlite"
        self.range_artifact = None
        if config.get("range_artifact"):
            from postflop_range_artifact import load_configured_artifact
            self.range_artifact = load_configured_artifact(config["_path"])
        self.active_config_hash = sha256_value(self.solver_config())
        for path in (self.candidate / "shards", self.work / "inputs", self.work / "results",
                     self.work / "reports", self.work / "checkpoints", self.work / "logs", self.releases):
            path.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def range_scenario(self, scene, permission):
        if self.range_artifact is None:
            return None
        key = (scene.get("action", {}).get("pot_type"),
               scene.get("effective_stack", {}).get("id"))
        matches = [item for item in self.range_artifact.get("scenarios", [])
                   if (item.get("pot_type"), item.get("stack_id")) == key]
        if len(matches) != 1:
            raise ToolUnavailableError(f"缺少可靠双方条件范围: {key[0]}/{key[1]}")
        scenario = matches[0]
        if scenario.get(permission) is not True:
            reasons = "; ".join(str(item) for item in scenario.get("block_reasons", []))
            raise ToolUnavailableError(
                f"缺少可靠双方条件范围: {key[0]}/{key[1]}" +
                (f" ({reasons[:300]})" if reasons else ""))
        return scenario

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _init_db(self):
        with self.connect() as connection:
            connection.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    scene_hash TEXT NOT NULL,
                    scene_json TEXT NOT NULL,
                    solver_config_hash TEXT NOT NULL,
                    solver_config_json TEXT NOT NULL,
                    shard_key TEXT NOT NULL,
                    seed INTEGER NOT NULL,
                    priority REAL NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    started_at TEXT,
                    finished_at TEXT,
                    iterations INTEGER,
                    convergence_name TEXT,
                    convergence_value REAL,
                    artifact_checksum TEXT,
                    error TEXT,
                    checkpoint_path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS tasks_status_priority ON tasks(status, priority DESC);
                CREATE TABLE IF NOT EXISTS artifacts (
                    scene_hash TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    shard_path TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    accepted_at TEXT NOT NULL
                );
            """)

    def solver_config(self):
        verification = json.loads(canonical_json(self.config["verification"]))
        cross = verification.get("cross_validation", {})
        cross.pop("kind", None)
        cross.pop("solver", None)
        cross.pop("evaluator", None)
        result = {
            "solver": {key: value for key, value in self.config["solver"].items()
                       if key not in ("command", "executable", "discover")},
            "acceptance": self.config["acceptance"],
            "verification": verification,
            "range_version": self.config["range_version"],
        }
        if self.range_artifact is not None:
            result["range_artifact_checksum"] = self.range_artifact["artifact_checksum"]
        return result

    def current_scene_hashes(self, solver_config_hash):
        pointer = self.root / "CURRENT"
        if not pointer.exists():
            return set()
        version = pointer.read_text(encoding="utf-8").strip()
        index = self.releases / version / "index.sqlite"
        if not index.exists():
            return set()
        connection = sqlite3.connect(index)
        try:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(strategies)")}
            if "solver_config_hash" not in columns:
                return set()
            return {row[0] for row in connection.execute(
                "SELECT scene_hash FROM strategies WHERE solver_config_hash=?", (solver_config_hash,)
            )}
        finally:
            connection.close()

    def runtime_gap_scenes(self):
        gap_file = Path(self.config.get("runtime_gap_file", "runtime_strategy_gaps.jsonl"))
        if not gap_file.is_absolute():
            gap_file = Path(self.config["_path"]).parent / gap_file
        if not gap_file.exists():
            return [], []
        scenes, errors = [], []
        with gap_file.open(encoding="utf-8") as source:
            for line_number, line in enumerate(source, 1):
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                    scene = item.get("scene_key", item)
                    validate_scene_key(scene, self.config)
                    metrics = item.get("metrics", {})
                    scenes.append((scene, metrics))
                except (ValueError, TypeError, json.JSONDecodeError) as error:
                    errors.append({"line": line_number, "error": str(error)[:300]})
        if errors:
            atomic_text(self.root / "invalid_runtime_gaps.json", canonical_json(errors))
        return scenes, errors

    def scan(self):
        gap_scenes, errors = self.runtime_gap_scenes()
        source = list(generated_scenes(self.config)) + gap_scenes
        solver_config = self.solver_config()
        config_hash = self.active_config_hash
        released = self.current_scene_hashes(config_hash)
        inserted = 0
        with self.connect() as connection:
            for scene, metrics in source:
                validate_scene_key(scene, self.config)
                scene_hash = sha256_value(scene)
                if scene_hash in released:
                    continue
                priority = (
                    float(metrics.get("frequency", 1.0))
                    * float(metrics.get("decision_value", 1.0))
                    * float(metrics.get("uncertainty", 1.0))
                    / max(float(metrics.get("compute_cost", 1.0)), 0.001)
                )
                task_id = hashlib.sha256(f"{scene_hash}:{config_hash}".encode()).hexdigest()
                checkpoint = self.work / "checkpoints" / task_id
                cursor = connection.execute("""
                    INSERT OR IGNORE INTO tasks(
                        task_id,scene_hash,scene_json,solver_config_hash,solver_config_json,
                        shard_key,seed,priority,status,checkpoint_path,created_at,updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                """, (task_id, scene_hash, canonical_json(scene), config_hash,
                      canonical_json(solver_config), shard_key(scene),
                      int(scene_hash[:8], 16) & 0x7fffffff, priority, "pending",
                      str(checkpoint), now(), now()))
                inserted += cursor.rowcount
        return {"discovered": len(source), "enqueued": inserted, "invalid": len(errors)}

    def recover(self):
        max_attempts = int(self.config["solver"].get("max_attempts", 3))
        with self.connect() as connection:
            connection.execute("UPDATE tasks SET status='pending', error='进程中断后恢复', updated_at=? WHERE status='running' AND solver_config_hash=?", (now(), self.active_config_hash))
            connection.execute("UPDATE tasks SET status='pending', updated_at=? WHERE status='blocked_solver' AND solver_config_hash=?", (now(), self.active_config_hash))
            connection.execute("UPDATE tasks SET status='awaiting_validation', updated_at=? WHERE status IN ('blocked_validation','failed_validation') AND solver_config_hash=?", (now(), self.active_config_hash))
            connection.execute("UPDATE tasks SET status='pending', updated_at=? WHERE status='failed' AND attempts < ? AND solver_config_hash=?", (now(), max_attempts, self.active_config_hash))
            if self.config["solver"].get("retry_rejected") is True:
                connection.execute(
                    "UPDATE tasks SET status='pending', updated_at=? WHERE status='rejected' AND attempts < ? AND solver_config_hash=?",
                    (now(), max_attempts, self.active_config_hash),
                )

    def claim(self, status):
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            task = connection.execute(
                "SELECT * FROM tasks WHERE status=? AND solver_config_hash=? ORDER BY priority DESC, created_at LIMIT 1",
                (status, self.active_config_hash),
            ).fetchone()
            if task:
                connection.execute(
                    "UPDATE tasks SET status='running', attempts=attempts+?, started_at=?, updated_at=?, error=NULL WHERE task_id=?",
                    (1 if status == "pending" else 0, now(), now(), task["task_id"]),
                )
            return dict(task) if task else None

    def raw_result_path(self, task_id):
        return self.work / "results" / f"{task_id}.json.gz"

    def run_solver(self, task):
        adapter = CommandAdapter(self.config["solver"], Path(self.config["_path"]).parent, "求解器")
        task_id = task["task_id"]
        scene = json.loads(task["scene_json"])
        range_scenario = self.range_scenario(scene, "solve_allowed")
        input_path = self.work / "inputs" / f"{task_id}.json"
        output_path = self.work / "results" / f"{task_id}.solver.json"
        checkpoint = Path(task["checkpoint_path"])
        checkpoint.mkdir(parents=True, exist_ok=True)
        solver_input = {
            "format_version": FORMAT_VERSION,
            "task_id": task_id,
            "scene_hash": task["scene_hash"],
            "scene_key": scene,
            "solver_config": json.loads(task["solver_config_json"]),
            "seed": task["seed"],
            "attempt": int(task["attempts"]) + 1,
            "checkpoint": str(checkpoint),
        }
        if range_scenario is not None:
            solver_input["range_scenario"] = range_scenario
            solver_input["range_artifact_checksum"] = self.range_artifact["artifact_checksum"]
        atomic_text(input_path, canonical_json(solver_input))
        adapter.run({
            "input": str(input_path), "output": str(output_path),
            "checkpoint": str(checkpoint), "task_id": task_id,
        }, self.work / "logs" / f"{task_id}.solver.log")
        if not output_path.exists():
            raise RuntimeError("求解器没有生成输出文件")
        result = json.loads(output_path.read_text(encoding="utf-8"))
        write_gzip_json(self.raw_result_path(task_id), result)
        solver = result.get("solver", {})
        with self.connect() as connection:
            connection.execute("""
                UPDATE tasks SET status='awaiting_validation',
                    iterations=?, convergence_name='exploitability_bb', convergence_value=?,
                    finished_at=?, updated_at=? WHERE task_id=?
            """, (solver.get("iterations"), solver.get("exploitability_bb"), now(), now(), task_id))

    def run_verifier(self, task, result, name):
        settings = self.config["verification"][name]
        adapter = CommandAdapter(settings, Path(self.config["_path"]).parent, name)
        task_id = task["task_id"]
        input_path = self.work / "reports" / f"{task_id}.{name}.input.json"
        report_path = self.work / "reports" / f"{task_id}.{name}.json"
        atomic_text(input_path, canonical_json(result))
        adapter.run({
            "input": str(input_path), "report": str(report_path),
            "task_id": task_id, "scene": str(self.work / "inputs" / f"{task_id}.json"),
        }, self.work / "logs" / f"{task_id}.{name}.log")
        if not report_path.exists():
            raise RuntimeError(f"{name}没有生成报告")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if report.get("passed") is not True and name != "cross_validation":
            raise ValueError(f"{name}未通过: {str(report.get('reason', 'unknown'))[:200]}")
        if name == "cross_validation" and report.get("passed") is True:
            delta = report.get("max_delta_bb")
            if not isinstance(delta, (int, float)) or delta < 0:
                raise ValueError("cross_validation缺少有效max_delta_bb")
        elif name != "cross_validation" and (
                not isinstance(report.get("cases"), int) or report["cases"] <= 0):
            raise ValueError("fixed_regression缺少有效cases")
        report["builder_execution"] = {
            "executed": True,
            "verified_at": now(),
            "config_hash": sha256_value(verification_execution_config(settings)),
        }
        return report

    def store_candidate(self, task, result, status="validated"):
        key = task["shard_key"]
        path = self.candidate / "shards" / f"{key}.json.gz"
        shard = read_gzip_json(path) if path.exists() else {
            "format_version": FORMAT_VERSION, "shard_key": key, "records": [],
        }
        record = {
            "scene_hash": task["scene_hash"],
            "scene_key": json.loads(task["scene_json"]),
            "solver_config_hash": task["solver_config_hash"],
            "result": result,
            "checksum": sha256_value(result),
        }
        records = {item["scene_hash"]: item for item in shard["records"]}
        records[task["scene_hash"]] = record
        shard["records"] = [records[item] for item in sorted(records)]
        write_gzip_json(path, shard)
        checksum = sha256_file(path)
        with self.connect() as connection:
            connection.execute("""
                INSERT INTO artifacts(scene_hash,task_id,shard_path,checksum,accepted_at)
                VALUES(?,?,?,?,?) ON CONFLICT(scene_hash) DO UPDATE SET
                    task_id=excluded.task_id,shard_path=excluded.shard_path,
                    checksum=excluded.checksum,accepted_at=excluded.accepted_at
            """, (task["scene_hash"], task["task_id"], str(path), checksum, now()))
            connection.execute("""
                UPDATE tasks SET status=?,artifact_checksum=?,finished_at=?,updated_at=?,error=NULL
                WHERE task_id=?
            """, (status, record["checksum"], now(), now(), task["task_id"]))

    def validate_task(self, task):
        result_path = self.raw_result_path(task["task_id"])
        if not result_path.exists():
            raise ValueError("断点中缺少求解结果")
        result = read_gzip_json(result_path)
        scene = json.loads(task["scene_json"])
        errors = validate_result(result, scene, self.config, require_verification=False)
        if errors:
            raise ValueError("; ".join(errors[:10]))
        verification = result.setdefault("verification", {})
        verification["fixed_regression"] = self.run_verifier(task, result, "fixed_regression")
        try:
            verification["cross_validation"] = self.run_verifier(task, result, "cross_validation")
        except ToolUnavailableError as error:
            verification["cross_validation"] = {
                "passed": False,
                "unavailable": True,
                "reason": str(error),
                "builder_execution": {"executed": False},
            }
            write_gzip_json(result_path, result)
            self.store_candidate(task, result, "candidate_unverified")
            return
        write_gzip_json(result_path, result)
        if independent_verification_errors(result, self.config):
            self.store_candidate(task, result, "candidate_unverified")
            return
        errors = validate_result(result, scene, self.config, require_verification=True)
        if errors:
            raise ValueError("; ".join(errors[:10]))
        self.store_candidate(task, result)

    def mark(self, task_id, status, error):
        with self.connect() as connection:
            connection.execute(
                "UPDATE tasks SET status=?,error=?,finished_at=?,updated_at=? WHERE task_id=?",
                (status, str(error)[:1000], now(), now(), task_id),
            )

    def status(self, stop_reason=None):
        self.reconcile_candidate_verification_status()
        with self.connect() as connection:
            counts = {row[0]: row[1] for row in connection.execute(
                "SELECT status,COUNT(*) FROM tasks WHERE solver_config_hash=? GROUP BY status",
                (self.active_config_hash,))}
            if stop_reason is None:
                row = connection.execute("""
                    SELECT error FROM tasks
                    WHERE status IN ('blocked_solver','blocked_validation','failed_validation','failed','rejected')
                      AND error IS NOT NULL AND solver_config_hash=?
                    ORDER BY updated_at DESC LIMIT 1
                """, (self.active_config_hash,)).fetchone()
                stop_reason = row[0] if row else None
        total = sum(counts.values())
        unverified_candidates = counts.get("candidate_unverified", 0)
        completed = counts.get("validated", 0) + unverified_candidates
        failed = counts.get("failed", 0) + counts.get("rejected", 0)
        blocked = counts.get("blocked_solver", 0) + counts.get("blocked_validation", 0)
        remaining = total - completed - failed
        files = list((self.candidate / "shards").glob("*.json.gz"))
        current_bytes = sum(path.stat().st_size for path in files)
        average = current_bytes / completed if completed else int(self.config.get("estimated_bytes_per_task", 2000000))
        payload = {
            "target": total,
            "completed": completed,
            "unverified_candidates": unverified_candidates,
            "failed": failed,
            "blocked": blocked,
            "remaining": remaining,
            "estimated_disk_bytes": int(current_bytes + average * max(0, remaining)),
            "stop_reason": stop_reason,
            "updated_at": now(),
        }
        atomic_text(self.root / "status.json", canonical_json(payload))
        return payload

    def reconcile_candidate_verification_status(self):
        records = self.candidate_records(self.active_config_hash)
        if not records:
            return
        with self.connect() as connection:
            for scene_hash, record in records.items():
                status = ("candidate_unverified"
                          if independent_verification_errors(record["result"], self.config)
                          else "validated")
                connection.execute("""
                    UPDATE tasks SET status=?,updated_at=?
                    WHERE scene_hash=? AND solver_config_hash=?
                      AND status IN ('validated','candidate_unverified')
                """, (status, now(), scene_hash, self.active_config_hash))

    def revalidate_candidates(self):
        records = self.candidate_records(self.active_config_hash)
        queued = 0
        with self.connect() as connection:
            for scene_hash, record in records.items():
                if not independent_verification_errors(record["result"], self.config):
                    continue
                task = connection.execute("""
                    SELECT task_id FROM tasks
                    WHERE scene_hash=? AND solver_config_hash=?
                """, (scene_hash, self.active_config_hash)).fetchone()
                if not task:
                    continue
                result_path = self.raw_result_path(task["task_id"])
                if not result_path.exists():
                    write_gzip_json(result_path, record["result"])
                connection.execute("""
                    UPDATE tasks SET status='awaiting_validation',error=NULL,updated_at=?
                    WHERE task_id=?
                """, (now(), task["task_id"]))
                queued += 1
        return queued

    def acquire_lock(self):
        lock = self.root / "builder.lock"
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(descriptor, str(os.getpid()).encode())
            os.close(descriptor)
            return lock
        except FileExistsError:
            raise RuntimeError("建库进程已经在运行；如确认异常退出，可删除 builder.lock 后续算")

    def run(self):
        lock = self.acquire_lock()
        stop_reason = None
        try:
            self.scan()
            self.recover()
            self.revalidate_candidates()
            while True:
                task = self.claim("awaiting_validation")
                phase = "validation"
                if not task:
                    task = self.claim("pending")
                    phase = "solver"
                if not task:
                    break
                try:
                    if phase == "solver":
                        self.run_solver(task)
                    else:
                        self.validate_task(task)
                except ToolUnavailableError as error:
                    blocked = "blocked_solver" if phase == "solver" else "blocked_validation"
                    self.mark(task["task_id"], blocked, error)
                    stop_reason = str(error)
                    if phase == "solver" and not str(error).startswith("缺少可靠双方条件范围:"):
                        with self.connect() as connection:
                            connection.execute(
                                "UPDATE tasks SET status='blocked_solver',error=?,updated_at=? WHERE status='pending' AND solver_config_hash=?",
                                (str(error)[:1000], now(), self.active_config_hash),
                            )
                except (ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
                    retry_validation = (
                        phase == "validation" and
                        self.config["solver"].get("retry_rejected") is True and
                        int(task["attempts"]) < int(self.config["solver"].get("max_attempts", 3))
                    )
                    self.mark(task["task_id"], "pending" if retry_validation else
                              ("rejected" if phase == "validation" else "failed"), error)
                except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                    message = str(error)
                    resource_block = phase == "solver" and any(token in message.lower() for token in (
                        "memory limit", "estimated compressed memory", "out of memory"))
                    status = ("blocked_solver" if resource_block else
                              ("failed_validation" if phase == "validation" else "failed"))
                    self.mark(task["task_id"], status, error)
                    if resource_block:
                        stop_reason = message
                        with self.connect() as connection:
                            connection.execute(
                                "UPDATE tasks SET status='blocked_solver',error=?,updated_at=? "
                                "WHERE status='pending' AND solver_config_hash=?",
                                (message[:1000], now(), self.active_config_hash),
                            )
            return self.status(stop_reason)
        finally:
            lock.unlink(missing_ok=True)

    def candidate_records(self, solver_config_hash=None):
        records = {}
        for path in sorted((self.candidate / "shards").glob("*.json.gz")):
            shard = read_gzip_json(path)
            for record in shard.get("records", []):
                if solver_config_hash and record.get("solver_config_hash") != solver_config_hash:
                    continue
                if record["scene_hash"] in records:
                    raise ValueError("候选库存在重复场景键")
                if record["scene_hash"] != sha256_value(record["scene_key"]):
                    raise ValueError("候选记录场景哈希错误")
                errors = validate_result(record["result"], record["scene_key"], self.config, False)
                regression = record["result"].get("verification", {}).get("fixed_regression", {})
                if regression.get("passed") is not True or not isinstance(regression.get("cases"), int) or regression["cases"] <= 0:
                    errors.append("缺少固定回归验证")
                if errors or record["checksum"] != sha256_value(record["result"]):
                    raise ValueError("候选产物验收失败: " + "; ".join(errors[:5]))
                records[record["scene_hash"]] = record
        return records

    def assert_independent_verification(self, records):
        failures = []
        for scene_hash, record in records.items():
            errors = independent_verification_errors(record["result"], self.config)
            if errors:
                failures.append(f"{scene_hash[:12]}: {'; '.join(errors)}")
        if failures:
            kind = self.config.get("verification", {}).get("cross_validation", {}).get("kind")
            label = ("缺少合格的独立验证" if kind in (
                "independent_strategy_evaluator", "independent_model_cross_check")
                else "缺少独立求解器验证")
            raise ValueError(label + "，只能保留候选，禁止发布: " + " | ".join(failures[:5]))

    def assert_independent_solver_verification(self, records):
        self.assert_independent_verification(records)

    def assert_publish_validation(self, records):
        for scene_hash, record in records.items():
            self.range_scenario(record["scene_key"], "publish_allowed")
            errors = validate_result(record["result"], record["scene_key"], self.config, True)
            if errors:
                raise ValueError(f"候选产物发布验收失败 {scene_hash[:12]}: {'; '.join(errors[:5])}")

    def release_records(self, version):
        if not version:
            return {}
        release = self.releases / safe_name(version)
        manifest = self.verify_release(version)
        records = {}
        for shard in manifest["shards"]:
            for record in read_gzip_json(release / shard["path"])["records"]:
                records[record["scene_hash"]] = record
        return records

    def publish(self, version, confirmed=False):
        if not confirmed:
            raise ValueError("发布必须显式传入 --confirm")
        version = safe_name(version)
        target = self.releases / version
        if target.exists():
            raise ValueError("发布版本已存在")
        candidates = self.candidate_records(self.active_config_hash)
        if not candidates:
            raise ValueError("没有通过验收的正式候选")
        pointer = self.root / "CURRENT"
        base_version = pointer.read_text(encoding="utf-8").strip() if pointer.exists() else None
        prior = self.release_records(base_version)
        records = {**prior, **candidates}
        self.assert_independent_verification(records)
        self.assert_publish_validation(records)
        added = sorted(set(candidates) - set(prior))
        changed = sorted(
            scene_hash for scene_hash in set(candidates) & set(prior)
            if candidates[scene_hash]["checksum"] != prior[scene_hash]["checksum"]
        )
        temporary = self.releases / f".{version}.tmp"
        if temporary.exists():
            shutil.rmtree(temporary)
        (temporary / "shards").mkdir(parents=True)
        grouped = {}
        for record in records.values():
            grouped.setdefault(shard_key(record["scene_key"]), []).append(record)
        manifest_shards = []
        index_path = temporary / "index.sqlite"
        connection = sqlite3.connect(index_path)
        try:
            connection.execute("""
                CREATE TABLE strategies(
                    scene_hash TEXT PRIMARY KEY, shard_path TEXT NOT NULL,
                    artifact_checksum TEXT NOT NULL, scene_json TEXT NOT NULL,
                    solver_config_hash TEXT NOT NULL
                )
            """)
            for key, items in sorted(grouped.items()):
                relative = Path("shards") / f"{key}.json.gz"
                path = temporary / relative
                payload = {"format_version": FORMAT_VERSION, "shard_key": key,
                           "records": sorted(items, key=lambda item: item["scene_hash"])}
                started = time.perf_counter()
                write_gzip_json(path, payload)
                read_gzip_json(path)
                latency_ms = (time.perf_counter() - started) * 1000
                if latency_ms > self.config["acceptance"]["max_shard_load_ms"]:
                    raise ValueError(f"分片 {key} 解压延迟超限")
                for item in items:
                    connection.execute("INSERT INTO strategies VALUES(?,?,?,?,?)", (
                        item["scene_hash"], str(relative).replace("\\", "/"), item["checksum"],
                        canonical_json(item["scene_key"]), item["solver_config_hash"],
                    ))
                manifest_shards.append({
                    "path": str(relative).replace("\\", "/"), "records": len(items),
                    "checksum": sha256_file(path), "load_latency_ms": round(latency_ms, 3),
                })
            connection.commit()
        finally:
            connection.close()
        manifest = {
            "format_version": FORMAT_VERSION,
            "release_version": version,
            "base_version": base_version,
            "library_schema_version": self.config["library_schema_version"],
            "created_at": now(),
            "records": len(records),
            "changes": {"added": added, "updated": changed},
            "independent_verification": {
                "required": True,
                "kind": self.config["verification"]["cross_validation"]["kind"],
                "identity": (
                    self.config["verification"]["cross_validation"].get("evaluator")
                    or self.config["verification"]["cross_validation"].get("solver")
                ),
            },
            "shards": manifest_shards,
            "index_checksum": sha256_file(index_path),
        }
        atomic_text(temporary / "manifest.json", canonical_json(manifest))
        os.replace(temporary, target)
        for path in target.rglob("*"):
            if path.is_file():
                path.chmod(0o444)
        atomic_text(self.root / "CURRENT", version)
        return manifest

    def verify_release(self, version):
        release = self.releases / safe_name(version)
        manifest_path = release / "manifest.json"
        if not manifest_path.exists():
            raise ValueError("目标发布版本不存在")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        settings = self.config.get("verification", {}).get("cross_validation", {})
        verification = manifest.get("independent_verification")
        if verification is None and settings.get("kind") == "independent_equilibrium_solver":
            legacy = manifest.get("independent_solver_verification", {})
            verification = {
                "required": legacy.get("required"),
                "kind": "independent_equilibrium_solver",
                "identity": legacy.get("solver"),
            }
        expected_identity = settings.get("evaluator") or settings.get("solver")
        if (verification.get("required") is not True
                or verification.get("kind") != settings.get("kind")
                or verification.get("identity") != expected_identity):
            raise ValueError("发布版本缺少匹配的独立验证门禁")
        if sha256_file(release / "index.sqlite") != manifest["index_checksum"]:
            raise ValueError("发布索引校验和错误")
        for shard in manifest["shards"]:
            if sha256_file(release / shard["path"]) != shard["checksum"]:
                raise ValueError("发布分片校验和错误")
        return manifest

    def rollback(self, version):
        manifest = self.verify_release(version)
        self.assert_independent_verification(self.release_records(version))
        atomic_text(self.root / "CURRENT", safe_name(version))
        return manifest


def print_summary(value):
    fields = ("target", "completed", "failed", "blocked", "remaining", "estimated_disk_bytes", "stop_reason")
    print(" ".join(f"{field}={value.get(field)}" for field in fields if field in value))


def main(argv=None):
    parser = argparse.ArgumentParser(description="本地零Token近似GTO候选库生成器")
    parser.add_argument("--config", default="strategy_library_builder.json")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("scan")
    commands.add_parser("run")
    commands.add_parser("status")
    publish = commands.add_parser("publish")
    publish.add_argument("--version", required=True)
    publish.add_argument("--confirm", action="store_true")
    rollback = commands.add_parser("rollback")
    rollback.add_argument("--version", required=True)
    args = parser.parse_args(argv)
    builder = StrategyLibraryBuilder(load_config(args.config))
    if args.command == "scan":
        print_summary(builder.scan())
    elif args.command == "run":
        print_summary(builder.run())
    elif args.command == "status":
        print_summary(builder.status())
    elif args.command == "publish":
        print(canonical_json(builder.publish(args.version, args.confirm)))
    elif args.command == "rollback":
        print(canonical_json(builder.rollback(args.version)))


if __name__ == "__main__":
    main()
