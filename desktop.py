import base64
import ctypes
import ctypes.wintypes
import hashlib
import io
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
import uuid
import http.server
import socketserver
import queue
import joblib
from collections import Counter, deque
from pathlib import Path
import tkinter as tk

import cv2
import numpy as np
import webview
from action_ledger_layer import ActionLedgerLayer
from action_chain_engine import ActionChainEngine
from shadow_action_engine import ShadowActionEngine
from action_evidence import EvidenceEvent
from action_engine import ActionEngine, ActionEventStore
from action_timeline import ActionTimeline
from capture_layer import CaptureLayer
from recognition_layer import RecognitionLayer
from hand_state_layer import HandStateLayer
from pipeline_runtime import PipelineRuntime
from card_state_layer import CardStateLayer
from node_tool_runner import node_executable
from table_info_parser import lookup_rake, parse_blind_text, parse_table_number, parse_table_play
from PIL import Image, ImageGrab
from rapidocr_onnxruntime import RapidOCR

cv2.setNumThreads(1)
from overlay_window import BORDER_WIDTH, OverlayWindow
from strategy_store import StrategyStore
from history_store import HistoryStore
from exploit_strategy import ExploitStrategyEngine
from recognition_state import FieldState, HandMachine, full_raise_count, minimum_raise_to, position_for
from pipeline_layers import pipeline_snapshot as build_pipeline_snapshot
from opponent_stats_capture import OpponentStatsParser
from table_tracker import TablePresenceTracker, border_color, capture_desktop, detect_table, enable_dpi_awareness
from v4.preflop_shadow_strategy import (
    baseline_range as preflop_baseline_range,
    evaluate_shadow as evaluate_preflop_shadow,
)
from v4.preflop_enumeration import (
    ACTION_PRESSURE as PREFLOP_ACTION_PRESSURE,
    POSITIONS_BY_PLAYERS as PREFLOP_POSITIONS_BY_PLAYERS,
    RAKE_POLICIES as PREFLOP_RAKE_POLICIES,
    STACK_BUCKETS as PREFLOP_STACK_BUCKETS,
    legal_scenario_families as preflop_legal_scenario_families,
)


enable_dpi_awareness()


APP_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
APP_VERSION = "2026.09.12.210"
TEMPLATE_FILE = APP_DIR / "card_templates.json"
RANK_TEMPLATE_FILE = APP_DIR / "reviewed_card_rank_templates.json"
HERO_AVATAR_FILE = APP_DIR / "hero_avatar.png"
DATA_DIR = Path.home() / ".poker-study-tool"
CONFIG_FILE = DATA_DIR / "capture.json"
DEFAULT_BBOX = [960, 30, 1920, 1050]
TABLE_LAYOUTS = {
    "8max": [(0.50, 0.13), (0.90, 0.235), (0.90, 0.404), (0.90, 0.587), (0.50, 0.774), (0.10, 0.587), (0.10, 0.404), (0.10, 0.237)],
    "6max": [(0.50, 0.142), (0.90, 0.31), (0.90, 0.59), (0.50, 0.775), (0.10, 0.59), (0.10, 0.31)],
}
DEALER_ANCHORS = {
    "8max": [(0.611, 0.195), (0.795, 0.288), (0.843, 0.477), (0.793, 0.641),
             (0.381, 0.809), (0.213, 0.641), (0.163, 0.477), (0.214, 0.288)],
    "6max": [(0.611, 0.194), (0.825, 0.365), (0.793, 0.641),
             (0.381, 0.809), (0.213, 0.641), (0.175, 0.365)],
}
ACTION_WORDS = {"post_blind": ("补盲", "盲注"), "raise": ("加注", "raise", "allin", "全下"),
                "bet": ("下注", "bet"), "call": ("跟注", "call"),
                "check": ("让牌", "过牌", "check", "횻탬"), "fold": ("弃牌", "fold")}
user32 = ctypes.windll.user32
GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008
HWND_TOPMOST = ctypes.c_void_p(-1)
HWND_NOTOPMOST = ctypes.c_void_p(-2)

ACTION_TEXT_WORDS = {
    "post_blind": ("\u8865\u76f2", "\u76f2\u6ce8"),
    "straddle": ("straddle", "stradl", "stradle", "sradl", "stadl", "\u8df3\u76f2", "\u8de8\u6ce8"),
    "allin": ("\u5168\u4e0b", "all in", "allin", "all-in"),
    "raise": ("\u52a0\u6ce8", "raise"),
    "bet": ("\u4e0b\u6ce8", "bet"),
    "call": ("\u8ddf\u6ce8", "call"),
    "check": ("\u8ba9\u724c", "\u8fc7\u724c", "check", "\ud69f\ud0ec", "횻탬"),
    "fold": ("\u5f03\u724c", "fold"),
}

ACTION_STRATEGY_CONFIDENCE = .82

CONFIDENCE_GATED_FIELDS = {
    "heroCards", "boardCards", "dealerIndex", "pot", "callAmount", "buttons",
    "tablePlay", "tableNumber", "blindTextRaw", "blindSmall", "blindBig", "blindStraddle", "blindAnte",
}

HAND_SCOPED_FIELDS = {
    "heroCards", "boardCards", "dealerIndex", "heroPosition", "pot", "callAmount", "buttons",
}

FAST_OWNED_FIELDS = {
    "heroCards", "visibleHeroCards", "boardCards", "visibleBoardCards",
    "handId", "street", "dealerIndex", "dealerReliable", "heroPosition",
    "visualHeroTurn", "visualButtons", "buttons", "heroTurn", "actionable", "reliable",
    "recognitionReliable", "actionQualityReliable",
    "pot", "callAmount", "minRaiseTo", "actionLog", "actionCandidates",
    "preflopFullRaiseCount", "participating", "participationEvidence", "spectator",
    "expectedActionSeat", "heroActsAfterExpected", "unactedPlayers",
    "decisionDataFrameCapturedAt", "decisionDataFrameSequence",
    "decisionDataFrameReceivedAt",
    "visualButtonFrameCapturedAt", "actionButtonDetectedAt",
    "actionButtonFrameCapturedAt", "actionButtonFrameReceivedAt", "actionButtonSequence",
    "actionButtonStatePublishedAt",
    "buttonRecognitionSource",
    "heroPreselection", "actionButtonPreselection",
    "decisionChipFrameCapturedAt", "decisionChipFrameSequence",
    "decisionChipStacks", "decisionChipHandId", "decisionChipStreet",
    "cardUpdatedAt", "cardFrameCapturedAt", "cardFrameSequence", "cardLatencyMs",
    "reactionEstimates",
}

SLOW_SEAT_FIELDS = {
    "name", "chips", "chipConfidence", "avatar", "avatarHash",
    "avatarReliable", "avatarPresent", "seatPresent", "confidence",
    "identityConfidence", "observedAt", "frameSequence", "videoSecond",
}

SLOW_STATE_FIELDS = {
    "layout", "tablePlay", "tableNumber", "tableIdentityOcr", "blindTextRaw",
    "blindSmall", "blindBig", "blindStraddle", "blindAnte", "rakeRate", "rakeCap", "rakePlayers", "rakeSource",
    "slowUpdatedAt", "seatStateFrameCapturedAt", "seatStateFrameSequence",
    "seatStateHandId", "seatStateStreet", "activePlayerCount",
    "opponentProfiles", "historyStatus",
}


def _png_bytes(image):
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def visible_windows():
    windows = []
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    @callback_type
    def callback(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        title = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title, length + 1)
        rect = ctypes.wintypes.RECT()
        user32.GetClientRect(hwnd, ctypes.byref(rect))
        point = ctypes.wintypes.POINT(0, 0)
        user32.ClientToScreen(hwnd, ctypes.byref(point))
        width, height = rect.right - rect.left, rect.bottom - rect.top
        if width > 100 and height > 100:
            windows.append({"hwnd": int(hwnd), "title": title.value, "bbox": [point.x, point.y, point.x + width, point.y + height]})
        return True

    user32.EnumWindows(callback, 0)
    return windows


def projection_window_for_region(windows, region=None):
    excluded_titles = ("capture audit", "poker study console", "chatgpt")
    recording_titles = (".mp4", ".mov", ".mkv", ".avi", "mpc-hc", "media player")
    region_area = None
    if region:
        region_area = max(1, (region[2] - region[0]) * (region[3] - region[1]))
    candidates = []
    for window in windows:
        title = window.get("title", "").lower()
        x1, y1, x2, y2 = window["bbox"]
        width, height = x2 - x1, y2 - y1
        if any(value in title for value in excluded_titles + recording_titles):
            continue
        if width < 300 or height < 800 or not .42 <= width / max(height, 1) <= .52:
            continue
        if region:
            overlap = max(0, min(x2, region[2]) - max(x1, region[0])) * max(0, min(y2, region[3]) - max(y1, region[1]))
            if overlap / region_area < .90:
                continue
            window_area = width * height
            if window_area < region_area or window_area > region_area * 1.50:
                continue
            candidates.append((overlap / region_area, -window_area, window))
        else:
            candidates.append((1, -(width * height), window))
    return max(candidates, default=(None, None, None), key=lambda item: item[:2])[2]


def recording_window_for_region(windows, region=None):
    recording_titles = (".mp4", ".mov", ".mkv", ".avi", "mpc-hc", "media player")
    candidates = []
    for window in windows:
        if not any(value in window.get("title", "").lower() for value in recording_titles):
            continue
        x1, y1, x2, y2 = window["bbox"]
        overlap = 1
        if region:
            overlap = max(0, min(x2, region[2]) - max(x1, region[0])) * max(0, min(y2, region[3]) - max(y1, region[1]))
            if not overlap:
                continue
        candidates.append((overlap, (x2 - x1) * (y2 - y1), window))
    return max(candidates, default=(None, None, None), key=lambda item: item[:2])[2]


class Api:
    def __init__(self, headless=False, data_dir=None):
        self.data_dir = Path(data_dir) if data_dir else DATA_DIR
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_id = uuid.uuid4().hex
        self.config = self._load_config()
        self.ocr = RapidOCR(intra_op_num_threads=1, inter_op_num_threads=1)
        self.button_ocr = RapidOCR(intra_op_num_threads=1, inter_op_num_threads=1)
        self.decision_chip_ocr = RapidOCR(intra_op_num_threads=1, inter_op_num_threads=1)
        self.decision_chip_ocr_lock = threading.Lock()
        self.button_ocr_cache = {}
        self.ocr_lock = threading.Lock()
        self.card_templates = self._load_templates()
        self.card_rank_templates = self._load_rank_templates()
        self.dealer_slot_boxes = self._load_dealer_slot_boxes()
        self.pending = {}
        self.stable = {}
        self.chip_observations = {}
        self.stable_chip_confidences = {}
        self.force_slow_snapshot = False
        self.initial_identity_pending = True
        self.initial_identity_deadline = 0.0
        self.startup_chip_scan_running = False
        self.startup_chip_scan_complete = False
        self.slow_refresh_event = threading.Event()
        self.previous_board_count = 0
        self.previous_pot = 0.0
        self.layout = self.config.get("layout", "8max")
        self.calibration_confirmed = True
        self.headless = headless
        self.overlay = None if headless else OverlayWindow()
        self.strategy_store = StrategyStore(self.data_dir)
        self.history_store = HistoryStore(self.data_dir)
        self.profile_calibration_running = False
        self.profile_calibration_lock = threading.Lock()
        self.exploit_strategy = ExploitStrategyEngine(APP_DIR / "exploit_strategy.json")
        self.reaction_estimate_cache_key = None
        self.reaction_estimate_cache = {"modelVersion": 1, "candidates": {}}
        self.mode = "assist"
        configured_strategy_mode = self.config.get("strategyMode", "auto")
        self.strategy_mode = (configured_strategy_mode if configured_strategy_mode in
                              {"auto", "strict_exploit"} else "auto")
        configured_action_engine_mode = self.config.get("actionEngineMode", "formal")
        self.action_engine_mode = (configured_action_engine_mode if configured_action_engine_mode in
                                   {"formal", "legacy"} else "formal")
        self.action_engine_status = "initializing"
        self.overlay_enabled = True
        self.action_log = []
        self.action_event_store = ActionEventStore(
            self.data_dir / "action-event-ledger.jsonl")
        self.shadow_action_engine = ShadowActionEngine()
        self.batch_b_action_engine = ActionEngine()
        self.action_timeline = ActionTimeline()
        self.folded_seats = set()
        self.action_candidates = []
        self.hand_history = []
        self.previous_actions = {}
        self.last_snapshot = None
        self.window = None
        self.training_support_window = None
        self.training_decision_state = {
            "status": "waiting", "reason": "等待本人决策和正式精算"
        }
        self.audit_window = None
        self.hero_profile_window = None
        self.hero_profile_visible = False
        self.hero_profile_topmost = False
        self.opponent_hands_window = None
        self.opponent_hands_visible = False
        self.opponent_hands_topmost = False
        self.deep_analysis = {"latest": None, "stages": {}}
        self.audit_file = self.data_dir / "capture-audit.jsonl"
        self.audit_review_file = self.data_dir / "capture-audit-reviews.jsonl"
        self.decision_latency_file = self.data_dir / "decision-latency.jsonl"
        self.decision_audit_file = self.data_dir / "decision-audit.jsonl"
        self.decision_audit_lock = threading.Lock()
        self.decision_audit_seen = set()
        self.decision_audit_seen_order = deque()
        self.strategy_comparison_file = self.data_dir / "strategy-comparison.jsonl"
        self.action_timeline_audit_file = self.data_dir / "action-timeline-audit.jsonl"
        self.action_engine_shadow_file = self.data_dir / "action-engine-shadow.jsonl"
        self.preflop_strategy_shadow_file = self.data_dir / "preflop-strategy-shadow.jsonl"
        self.preflop_strategy_shadow_seen = set()
        self.card_diagnostic_file = self.data_dir / "card-diagnostics.jsonl"
        self.peek_audit_file = self.data_dir / "peek-audit.jsonl"
        self.peek_diagnostic_file = self.data_dir / "peek-diagnostics.jsonl"
        self.profile_statistics_audit_file = self.data_dir / "profile-statistics-audit.jsonl"
        self.profile_statistics_snapshot_dir = self.data_dir / "profile-statistics-snapshots"
        self.hero_profile_file = self.data_dir / "hero-profile.json"
        self.deep_analysis_file = self.data_dir / "deep-analysis.jsonl"
        self.hero_profile = self._load_hero_profile()
        self.hero_range_seen = set()
        self._backfill_hero_range_history()
        self.card_diagnostic_last = {}
        self.audit_crop_cache = {}
        self.audit_crop_sequence = -1
        self.audit_crop_at = 0.0
        self.audit_visible = True
        self.windows_docked = True
        self.windows_topmost = True
        self.shutting_down = False
        self.decision_audit_snapshot = None
        self.hero_range_decision_snapshot = None
        self.pending_hero_decisions = {}
        self.decision_latency_samples = deque(maxlen=500)
        self.shadow_strategy_comparisons = self._load_shadow_strategy_comparisons()
        self.action_button_sequence = 0
        self.hero_preselection = None
        self.hero_preselection_candidate = None
        self.hero_preselection_candidate_frame_sequence = None
        self.hero_preselection_candidate_frames = 0
        self.hero_preselection_clear_frames = 0
        self.hero_preselection_clear_frame_sequence = None
        self.action_button_preselection = None
        self.visual_turn_detected = False
        self.action_button_detected_at = None
        self.action_button_frame_captured_at = None
        self.action_button_frame_received_at = None
        self.action_button_frame_sequence = None
        self.hero_button_last_visible_frame_sequence = None
        self.hero_button_last_visible_hand_id = None
        self.hero_button_last_visible_street = None
        self.visual_turn_hand_id = None
        self.visual_turn_street = None
        self.last_pushed_action_button_sequence = 0
        self.last_pushed_strategy_state_key = None
        self.state_push_callback = None
        self.action_button_missing_frames = 0
        self.action_button_opportunity = None
        self.button_ocr_fallback_last_at = 0.0
        self.button_ocr_fallback_last_frame_sequence = None
        self.action_button_fragments = None
        self.action_audit_snapshots = []
        self.pending_action_audits = []
        self.previous_hero_bet = 0.0
        self.previous_hero_chips = None
        self.previous_buttons = []
        self.pending_hero_buttons = []
        self.pending_hero_chips = None
        self.pending_hero_started = 0.0
        self.pending_hero_second = None
        self.pending_hero_frames = 0
        self.pending_hero_hand_id = None
        self.pending_hero_street = None
        self.hero_decision_chips = None
        self.hero_last_official_buttons = []
        self.hero_last_official_chips = None
        self.hero_last_official_second = None
        self.hero_button_release_context = None
        self.fast_hero_empty_frames = 0
        self.fast_hero_buttons = []
        self.fast_hero_buttons_second = None
        self.fast_hero_no_button_frames = 0
        self.last_fast_hand_start_second = None
        saved_bbox = self.config.get("bbox")
        self.tracked_bbox = list(map(int, saved_bbox)) if isinstance(saved_bbox, list) and len(saved_bbox) == 4 else None
        self.capture_bbox_locked = bool(self.config.get("captureLocked") and self.tracked_bbox)
        self.border_color = "#fff200"
        self.participating_locked = False
        self.leave_evidence_frames = 0
        self.hand_active = False
        self.hand_id = 0
        self.current_hand = {}
        self.last_reliable_snapshot = None
        self.last_hero_cards = []
        self.hero_cards_present = False
        self.locked_hero_cards = []
        self.locked_hero_hand_id = 0
        self.table_state = {"layout": self.layout, "pendingLayout": None, "pendingFrames": 0, "activePlayerCount": 0}
        self.seat_occupancy_trace = deque(maxlen=500)
        self.fast_occupancy_signatures = {}
        self.fast_occupancy_candidates = {}
        self.fast_occupancy_last_scan_at = 0.0
        self.hand_state = {"active": False, "id": 0, "street": "preflop", "pot": None, "boardCards": [], "heroCards": []}
        self.seat_trackers = {}
        self.hero_evidence = {"name": False, "avatar": False, "cards": False, "nameText": ""}
        self.last_dealer_index = None
        self.pending_dealer_index = None
        self.pending_dealer_frames = 0
        self.fast_dealer_candidate = None
        self.fast_dealer_frames = 0
        self.fast_dealer_changed = False
        self.fast_dealer_locked_at = 0.0
        self.dealer_monitor_current = None
        self.dealer_monitor_missing_at = None
        self.dealer_monitor_candidate = None
        self.dealer_monitor_candidate_frames = 0
        self.dealer_monitor_candidate_at = None
        self.dealer_monitor_scene_blocked = False
        self.dealer_monitor_events = deque(maxlen=100)
        self.fast_board_candidate = []
        self.fast_board_frames = 0
        self.last_street_change_at = 0.0
        self.current_hand_seen_profiles = set()
        self.hand_dealer_index = None
        self.dealer_conflict = None
        self.fast_action_signatures = {}
        self.hand_closed = False
        self.waiting_for_forced_bets = False
        self.forced_bet_seats = {}
        self.hand_winners = []
        self.forced_bets_ready = False
        self.blind_amounts = {"small": None, "big": None}
        self.blind_straddle = None
        self.blind_currency = "usd"
        self.blind_text_candidate = None
        self.blind_text_frames = 0
        self.blind_text_raw = ""
        self.rake_rate = None
        self.rake_cap = None
        self.rake_players = None
        self.rake_source = None
        self.table_play = None
        self.table_number = None
        self.table_number_candidate = None
        self.table_number_frames = 0
        self.table_identity_reacquiring = False
        self.table_identity_previous_number = None
        self.table_identity_ocr = ""
        self.blind_ante = None
        self.hand_started_second = None
        self.hand_boundary_confirmed = False
        self.pending_history_events = []
        self.history_last_hand_id = None
        self.action_state_lock = threading.RLock()
        self.capture_lock = threading.Lock()
        self.capture_layer = CaptureLayer(buffer_seconds=10.0)
        self.recognition_layer = RecognitionLayer()
        self.latest_table_frame = None
        self.latest_capture_bbox = None
        self.latest_frame_captured_at = None
        self.latest_frame_video_second = None
        self.latest_frame_sequence = 0
        self.latest_frame_context = None
        self.frame_received_at = {}
        self.frame_buffer_seconds = self.capture_layer.buffer_seconds
        self.frame_buffer = deque()
        self.frame_buffer_lock = threading.Lock()
        self.frame_buffer_queue = queue.Queue(maxsize=4)
        self.frame_buffer_dropped = 0
        self.pipeline_timestamps = deque(maxlen=500)
        self.action_ocr_queue = queue.PriorityQueue(maxsize=32)
        self.action_ocr_sequence = 0
        self.action_ocr_sequence_lock = threading.Lock()
        self.action_ocr_ready = threading.Event()
        self._action_ocr_ready_lock = threading.Lock()
        self._action_ocr_ready_count = 0
        self._action_ocr_worker_target = 0
        self.avatar_ocr_queue = queue.PriorityQueue(maxsize=16)
        self.avatar_ocr_sequence = 0
        self.avatar_ocr_sequence_lock = threading.Lock()
        self.avatar_ocr_ready = threading.Event()
        self._avatar_ocr_ready_lock = threading.Lock()
        self._avatar_ocr_ready_count = 0
        self._avatar_ocr_worker_target = 0
        self.ocr_warmup_errors = []
        self.action_ocr_results = queue.Queue()
        self.center_ocr_queue = queue.Queue(maxsize=1)
        self.center_ocr_results = queue.Queue()
        self.center_ocr_cache = {}
        self.center_ocr_pending_hash = None
        self.center_pot_candidate = None
        self.peek_queue = queue.Queue(maxsize=1)
        self.peek_results = queue.Queue()
        self.peek_state = {"available": False, "triggered": False, "cost": None,
                           "usageCount": 0, "totalCost": 0.0, "revealedCards": [],
                           "source": None, "observedAt": None, "confirmedAt": None}
        self.profile_statistics_capture = {
            "status": "idle", "message": "点击对手头像后自动采集",
            "capturedAt": None, "player": None, "seat": None, "statistics": None,
        }
        self.profile_popup_capture_active = False
        self.profile_popup_capture_generation = 0
        self.pending_profile_statistics = None
        self.pending_profile_statistics_queue = deque()
        self.profile_confirmed_names = {}
        self.profile_statistics_lock = threading.Lock()
        self.profile_scene_active = False
        self.profile_auto_capture_inflight = False
        self.profile_auto_capture_completed = False
        self.profile_auto_capture_attempts = 0
        self.profile_auto_next_attempt_at = 0.0
        self.peek_candidate_visible = False
        self.peek_candidate_confirmed = False
        self.peek_candidate_started_at = 0.0
        self.peek_candidate_observations = 0
        self.peek_epoch = 0
        self.peek_last_probe_at = 0.0
        self.peek_reveal_deadline = 0.0
        self.peek_reveal_epoch = 0
        self.peek_reveal_started_at = 0.0
        self.peek_reveal_votes = {}
        self.peek_reveal_observation_count = 0
        self.action_ocr_dropped = 0
        self.action_ocr_completed = 0
        self.action_ocr_trace = deque(maxlen=500)
        self.action_trigger_counts = {}
        self.action_ocr_pending_seats = set()
        self.action_ocr_deferred_jobs = {}
        self.action_ocr_pending_lock = threading.Lock()
        self.avatar_ocr_pending_seats = set()
        self.avatar_ocr_deferred_jobs = {}
        self.avatar_ocr_pending_lock = threading.Lock()
        self.action_crop_history = {index: deque(maxlen=3) for index in range(8)}
        self.action_unresolved_retries = {index: 0 for index in range(8)}
        self.active_color_actions = {index: None for index in range(8)}
        self.action_capsule_epochs = {index: 0 for index in range(8)}
        self.action_capsule_last_seen = {index: None for index in range(8)}
        self.hand_start_capsule_epochs = {}
        self.hand_start_visible_capsules = set()
        self.action_capsule_visible = {index: False for index in range(8)}
        self.last_color_event_seat = None
        self.formal_expected_seat = None
        self.hand_dealers = {}
        self.hand_participants = {}
        self.hand_player_counts = {}
        self.hand_chip_history = {}
        self.decision_chip_recovery_sequence = None
        self.decision_chip_recovery_attempts = 0
        self.decision_chip_frame_cache = None
        self.forced_action_overrides = {}
        self.completed_hand_actions = []
        self.completed_hand_candidates = []
        self.pending_hand_boundary_forced = []
        self.avatar_fold_model = self._load_avatar_fold_model()
        try:
            from avatar_state_classifier import AvatarStateClassifier
            self.avatar_state_classifier = AvatarStateClassifier(self)
        except (OSError, ValueError):
            self.avatar_state_classifier = None
        self.avatar_fold_frames = {index: 0 for index in range(8)}
        self.avatar_state_latched = {index: False for index in range(8)}
        self.avatar_state_clear_frames = {index: 0 for index in range(8)}
        self.expected_avatar_scan_at = {}
        self.expected_action_probe_at = {}
        self.avatar_contrast_history = {index: deque(maxlen=20) for index in range(8)}
        self.seat_slot_boxes = self._load_seat_slot_boxes()
        try:
            from action_slot_classifier import ActionSlotClassifier
            self.action_slot_classifier = ActionSlotClassifier(
                self, APP_DIR / "action-templates" / "labels.json")
        except (OSError, ValueError, KeyError):
            self.action_slot_classifier = None
        self.card_candidates = {"heroCards": [], "boardCards": []}
        self.card_candidate_frames = {"heroCards": 0, "boardCards": 0}
        self.card_published = {"heroCards": [], "boardCards": []}
        self.card_visible = {"heroCards": [], "boardCards": []}
        self.card_visible_frame_sequence = -1
        self.card_last_frame_sequence = {"heroCards": -1, "boardCards": -1}
        self.card_state_lock = threading.RLock()
        self.card_publish_trace = deque(maxlen=500)
        self.fields = FieldState()
        self.hand_machine = HandMachine()
        self.state_lock = threading.RLock()
        self.cached_state = None
        self.fast_seat_snapshot = []
        self.fast_seat_snapshot_at = None
        self.recognition_started = False
        self.pipeline_runtime = PipelineRuntime(self)
        self.recognition_active = threading.Event()
        self.recognition_requested = False
        self.table_presence = TablePresenceTracker()
        self.table_session = 0
        self.table_status = "正在寻找牌桌"
        self.table_events = []
        self.special_scene_blocked_until = 0.0
        self.special_scene_last_frame_sequence = -1
        self.dealer_blocked_until_board_clear = False
        self.dealer_board_clear_since = None
        self.dealer_stale_board_pending = False
        self.dealer_stale_board_frames = 0
        self.last_audit_snapshot_signature = None
        self.last_audit_snapshot_at = 0.0
        self.audit_log_max_bytes = 16 * 1024 * 1024
        self.audit_log_backup_count = 10
        self.decision_audit_max_bytes = 50 * 1024 * 1024
        self.decision_audit_backup_count = 10
        self.audit_log_min_interval = 1.0

    @staticmethod
    def _load_seat_slot_boxes():
        root = APP_DIR / "outputs" / "wepoker-dictionary-rules-v2" / "frozen-dictionaries"
        boxes = {}
        for index in range(8):
            path = root / f"seat{index + 1}.json"
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                action_index = 3 if index == 0 else (5 if index == 4 else 4)
                investment_index = 5 if index == 0 else (6 if index == 4 else 5)
                chips_index = 4 if index in (0, 4) else 3
                slots = {item["index"]: item["box"] for item in data["slots"]}
                item = {"name": slots[1], "avatar": slots[2], "chips": slots[chips_index],
                        "action": slots[action_index], "investment": slots[investment_index],
                        "reference": data.get("referenceSize", [888, 1920])}
                if 8 in slots and 9 in slots:
                    item.update(leftButton=slots[8], rightButton=slots[9])
                boxes[index] = item
            except (OSError, ValueError, KeyError, StopIteration):
                continue
        return boxes

    @staticmethod
    def _load_dealer_slot_boxes():
        root = APP_DIR / "outputs" / "wepoker-dictionary-rules-v2" / "frozen-dictionaries"
        boxes = {}
        for index in range(8):
            try:
                data = json.loads((root / f"seat{index + 1}.json").read_text(encoding="utf-8"))
                slot_index = 7 if index == 4 else 6
                slot = next(item for item in data["slots"] if item["index"] == slot_index)
                boxes[index] = {"box": slot["box"], "reference": data.get("referenceSize", [888, 1920])}
            except (OSError, ValueError, KeyError, StopIteration):
                continue
        return boxes

    def _dealer_slot_box(self, index, width, height):
        item = self.dealer_slot_boxes.get(index)
        if not item:
            return None
        x1, y1, x2, y2 = self._reviewed_slot_box(item["box"], width, height, item["reference"])
        margin_x = max(3, round((x2 - x1) * .10))
        margin_y = max(3, round((y2 - y1) * .12))
        return (max(0, x1 - margin_x), max(0, y1 - margin_y),
                min(width, x2 + margin_x), min(height, y2 + margin_y))

    def _seat_slot_box(self, index, kind, width, height):
        item = self.seat_slot_boxes.get(index)
        if not item:
            return None
        reference_width, reference_height = item["reference"]
        scale = min(width / reference_width, height / reference_height)
        offset_x = round((width - reference_width * scale) / 2)
        offset_y = round((height - reference_height * scale) / 2)
        x1, y1, x2, y2 = item[kind]
        return (offset_x + round(x1 * scale), offset_y + round(y1 * scale),
                offset_x + round(x2 * scale), offset_y + round(y2 * scale))

    def _hero_preselection_box(self, side, width, height):
        hero_index = 4 if self.layout == "8max" else 3
        kind = "leftButton" if side == "left" else "rightButton"
        if kind in self.seat_slot_boxes.get(hero_index, {}):
            return self._seat_slot_box(hero_index, kind, width, height)
        return None

    def _detect_hero_preselection_visual(self, frame):
        height, width = frame.shape[:2]
        metrics = {}
        for side in ("left", "right"):
            box = self._hero_preselection_box(side, width, height)
            if box is None:
                return None
            x1, y1, x2, y2 = box
            crop = frame[max(0, y1):min(height, y2), max(0, x1):min(width, x2)]
            if crop.size == 0:
                return None
            hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            crop_height, crop_width = gray.shape
            yy, xx = np.ogrid[:crop_height, :crop_width]
            ellipse = (((xx - crop_width * .5) / max(1, crop_width * .22)) ** 2 +
                       ((yy - crop_height * .555) / max(1, crop_height * .22)) ** 2) <= 1
            pixels = hsv[ellipse]
            red = (((pixels[:, 0] <= 12) | (pixels[:, 0] >= 165)) &
                   (pixels[:, 1] >= 80) & (pixels[:, 2] >= 70))
            green = ((pixels[:, 0] >= 35) & (pixels[:, 0] <= 85) &
                     (pixels[:, 1] >= 70) & (pixels[:, 2] >= 35))
            edges = cv2.Canny(gray, 40, 100)
            metrics[side] = {
                "redRatio": round(float(np.mean(red)), 4),
                "greenRatio": round(float(np.mean(green)), 4),
                "darkRatio": round(float(np.mean(pixels[:, 2] < 105)), 4),
                "edgeRatio": round(float(np.mean(edges > 0)), 4),
            }
        gray = {
            side: metrics[side]["redRatio"] < .10 and
                  metrics[side]["greenRatio"] < .25 and
                  metrics[side]["darkRatio"] >= .15 and
                  metrics[side]["edgeRatio"] >= .008
            for side in ("left", "right")
        }
        left_selected = metrics["left"]["redRatio"] >= .45 and gray["right"]
        right_selected = (metrics["right"]["greenRatio"] >= .60 and
                          metrics["right"]["darkRatio"] >= .08 and
                          metrics["right"]["edgeRatio"] >= .008 and gray["left"])
        if left_selected == right_selected:
            return ({"selected": False, "visible": True, "metrics": metrics,
                     "confidence": .90} if all(gray.values()) else None)
        side = "left" if left_selected else "right"
        return {"selected": True, "side": side,
                "family": "fold_or_check_fold" if side == "left" else "check_or_call",
                "metrics": metrics, "confidence": .92}

    def _matching_hero_preselection(self):
        item = self.hero_preselection
        if (not item or item.get("handId") != self.hand_state.get("id") or
                item.get("street") != self.hand_state.get("street")):
            return None
        return item

    def _update_hero_preselection(self, frame, turn_confirmed, observed_at,
                                  frame_sequence, video_second=None):
        current = self._matching_hero_preselection()
        if len(self.card_published.get("heroCards", [])) != 2:
            return current
        if turn_confirmed or self._hero_action_countdown_visible(frame):
            return current
        detected = self._detect_hero_preselection_visual(frame)
        if detected and detected.get("selected"):
            signature = (self.hand_state.get("id"), self.hand_state.get("street"),
                         detected["side"])
            if (signature == self.hero_preselection_candidate and
                    frame_sequence != self.hero_preselection_candidate_frame_sequence):
                self.hero_preselection_candidate_frames += 1
            elif signature != self.hero_preselection_candidate:
                self.hero_preselection_candidate = signature
                self.hero_preselection_candidate_frames = 1
            self.hero_preselection_candidate_frame_sequence = frame_sequence
            self.hero_preselection_clear_frames = 0
            self.hero_preselection_clear_frame_sequence = None
            if self.hero_preselection_candidate_frames >= 2:
                self.hero_preselection = {
                    **detected, "handId": self.hand_state.get("id"),
                    "street": self.hand_state.get("street"), "observedAt": observed_at,
                    "frameSequence": frame_sequence, "videoSecond": video_second,
                    "evidence": "reviewed_preselection_slots+single_colored_circle+no_countdown",
                }
            return self._matching_hero_preselection()
        self.hero_preselection_candidate = None
        self.hero_preselection_candidate_frame_sequence = None
        self.hero_preselection_candidate_frames = 0
        if (current and detected and detected.get("visible") and
                frame_sequence != self.hero_preselection_clear_frame_sequence):
            self.hero_preselection_clear_frames += 1
            self.hero_preselection_clear_frame_sequence = frame_sequence
            if self.hero_preselection_clear_frames >= 2:
                self.hero_preselection = None
                self.hero_preselection_clear_frames = 0
                self.hero_preselection_clear_frame_sequence = None
        elif detected is None:
            self.hero_preselection_clear_frames = 0
            self.hero_preselection_clear_frame_sequence = None
        return self._matching_hero_preselection()

    @staticmethod
    def _reviewed_slot_box(box, width, height, reference=(888, 1920)):
        return RecognitionLayer.scale_box(box, width, height, reference)

    @staticmethod
    def _load_avatar_fold_model():
        path = APP_DIR / "outputs" / "wepoker-dictionary-rules-v2" / "avatar-fold-svm.joblib"
        try:
            return joblib.load(path)
        except (OSError, ValueError):
            return None

    def _avatar_is_fold(self, crop):
        if self.avatar_fold_model is None or crop.size == 0:
            return False
        image = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        height, width = image.shape
        image = image[int(height * .18):int(height * .92), int(width * .08):int(width * .92)]
        image = cv2.resize(image, (48, 32), interpolation=cv2.INTER_AREA)
        image = cv2.equalizeHist(image).astype(np.float32) / 255.0
        gradient_x = cv2.Sobel(image, cv2.CV_32F, 1, 0, ksize=3)
        gradient_y = cv2.Sobel(image, cv2.CV_32F, 0, 1, ksize=3)
        feature = np.concatenate([image.ravel(), gradient_x.ravel(), gradient_y.ravel()])
        return int(self.avatar_fold_model.predict([feature])[0]) == 1

    def _avatar_is_fold_for_frame(self, index, crop, frame_sequence):
        if getattr(self, "_avatar_fold_cache_frame", None) != frame_sequence:
            self._avatar_fold_cache_frame = frame_sequence
            self._avatar_fold_cache = {}
        cache = self._avatar_fold_cache
        if index not in cache:
            cache[index] = self._avatar_is_fold(crop)
        return cache[index]

    def bind_window(self, window, audit_window=None, hero_profile_window=None,
                    opponent_hands_window=None, training_support_window=None):
        if self.headless:
            return
        self.window = window
        self.training_support_window = training_support_window
        self.audit_window = audit_window
        self.hero_profile_window = hero_profile_window
        self.opponent_hands_window = opponent_hands_window
        self._start_dock_tracker()

    def _load_hero_profile(self):
        try:
            value = json.loads(self.hero_profile_file.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_hero_profile(self):
        self.hero_profile["version"] = 2
        self.hero_profile["updatedAt"] = time.time()
        temporary = self.hero_profile_file.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.hero_profile, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.hero_profile_file)

    def _backfill_hero_range_history(self):
        if self.hero_profile.get("historyBackfillVersion") == 1:
            return
        history_file = self.data_dir / "hand_history.jsonl"
        hands = {}
        try:
            with history_file.open("r", encoding="utf-8") as handle:
                for line in handle:
                    try:
                        item = json.loads(line)
                    except ValueError:
                        continue
                    if item.get("type") != "snapshot":
                        continue
                    hand_class = self._starting_hand_class(item.get("heroCards"))
                    hand_key = item.get("handKey")
                    if not hand_class or not hand_key:
                        continue
                    record = hands.setdefault(hand_key, {
                        "class": hand_class, "entered": False,
                        "position": item.get("heroPosition", "unknown"),
                    })
                    if record["position"] == "unknown" and item.get("heroPosition"):
                        record["position"] = item["heroPosition"]
                    hero_seat = next((seat.get("index") + 1 for seat in item.get("seats", [])
                                      if str(seat.get("name") or "").casefold() == "zixia888"), 5)
                    if any(event.get("seat") == hero_seat and
                           event.get("street") == "preflop" and
                           event.get("action") in ("call", "bet", "raise", "reraise", "allin")
                           for event in item.get("events", [])):
                        record["entered"] = True
        except OSError:
            hands = {}
        matrix = self.hero_profile.setdefault("matrix", {})
        for record in hands.values():
            group = self._hero_position_group(record["position"])
            buckets = ["all"] + ([] if group == "unknown" else [group])
            for bucket in buckets:
                cell = matrix.setdefault(bucket, {}).setdefault(
                    record["class"], {"dealt": 0, "entered": 0})
                cell["dealt"] += 1
                cell["entered"] += int(record["entered"])
        self.hero_profile["historyBackfillVersion"] = 1
        self.hero_profile["historyBackfillHands"] = len(hands)
        self._save_hero_profile()

    @staticmethod
    def _starting_hand_class(cards):
        if not isinstance(cards, (list, tuple)) or len(cards) != 2:
            return None
        ranks = "23456789TJQKA"
        try:
            first, second = cards
            ordered = sorted((first[0], second[0]), key=ranks.index, reverse=True)
        except (IndexError, ValueError, TypeError):
            return None
        if ordered[0] == ordered[1]:
            return ordered[0] * 2
        suited = len(first) > 1 and len(second) > 1 and first[1] == second[1]
        return "".join(ordered) + ("s" if suited else "o")

    @staticmethod
    def _hero_position_group(position):
        if position in ("under_the_gun", "under_the_gun_plus_one"):
            return "early"
        if position in ("middle", "hijack"):
            return "middle"
        if position in ("cutoff", "dealer"):
            return "late"
        if position in ("small_blind", "big_blind", "straddle"):
            return "blinds"
        return "unknown"

    def _observe_hero_range(self, hand_id, cards, position):
        if self.hero_profile.get("rangeCollectionActive", True) is False:
            return
        hand_class = self._starting_hand_class(cards)
        if not hand_class or not isinstance(hand_id, int) or hand_id <= 0:
            return
        hand_key = f"{self.runtime_id}:{hand_id}"
        group = self._hero_position_group(position)
        matrix = self.hero_profile.setdefault("matrix", {})
        changed = False
        if (hand_key, "dealt") not in self.hero_range_seen:
            self.hero_range_seen.add((hand_key, "dealt"))
            for bucket in ("all", group):
                if bucket == "unknown" and group != "unknown":
                    continue
                record = matrix.setdefault(bucket, {}).setdefault(
                    hand_class, {"dealt": 0, "entered": 0})
                record["dealt"] += 1
            changed = True
        hero_seat = 4 if self.layout == "6max" else 5
        entered = any(
            event.get("handId") == hand_id and event.get("street") == "preflop" and
            event.get("seat") == hero_seat and
            event.get("action") in ("call", "bet", "raise", "reraise", "allin")
            for event in self.action_log
        )
        if entered and (hand_key, "entered") not in self.hero_range_seen:
            self.hero_range_seen.add((hand_key, "entered"))
            for bucket in ("all", group):
                if bucket == "unknown" and group != "unknown":
                    continue
                matrix.setdefault(bucket, {}).setdefault(
                    hand_class, {"dealt": 1, "entered": 0})["entered"] += 1
            changed = True
        if changed:
            self._save_hero_profile()

    def start_recognition(self):
        self._start_recognition_workers()
        self._schedule_profile_calibration()
        self._wait_for_ocr_ready(1.5)
        self.recognition_requested = True
        if self.profile_popup_capture_active:
            return {"started": False, "status": "头像资料弹窗采集中；关闭弹窗后自动恢复识别"}
        self.initial_identity_pending = True
        self.initial_identity_deadline = time.time() + 6.0
        self.startup_chip_scan_complete = False
        self.force_slow_snapshot = True
        self.recognition_active.set()
        self.slow_refresh_event.set()
        return {"started": True, "status": "识别已启动"}

    def stop_recognition(self):
        self.recognition_requested = False
        self.pipeline_runtime.stop()
        return {"started": False, "status": "识别已停止，保留最后一次结果"}

    @staticmethod
    def _profile_name_compatible(left, right):
        raw_left, raw_right = str(left or "").strip(), str(right or "").strip()
        normalize = lambda value: re.sub(r"[\s.。…]+", "", value).casefold()
        left, right = normalize(raw_left), normalize(raw_right)
        if not left or not right:
            return False
        if left == right:
            return True
        left_short = bool(re.search(r"(?:\.{2,}|…)$", raw_left))
        right_short = bool(re.search(r"(?:\.{2,}|…)$", raw_right))
        return min(len(left), len(right)) >= 2 and (
            left_short and right.startswith(left) or right_short and left.startswith(right))

    def _profile_statistics_seat(self, name):
        with self.state_lock:
            seats = [dict(seat) for seat in (self.cached_state or {}).get("seats", [])]
        seats = [seat for seat in seats if not seat.get("isHero") and not seat.get("empty")]
        normalize = lambda value: re.sub(r"[\s.。…]+", "", str(value or "")).casefold()
        target = normalize(name)
        if not target:
            raise ValueError("弹窗名称为空，无法绑定当前座位")

        def uniquely_bound(candidates, source, prefix_confirmed=False):
            if len(candidates) == 1:
                seat = dict(candidates[0])
            elif len(candidates) > 1:
                target_key = f"name:{target}"
                profile = self.history_store.profiles.get(target_key) or {}
                known_hashes = set(profile.get("avatarHashes") or ())
                if profile.get("avatarHash"):
                    known_hashes.add(profile["avatarHash"])
                confirmed = []
                for candidate in candidates:
                    identity = self.history_store.session_identities.get(candidate.get("index")) or {}
                    if (identity.get("key") == target_key or normalize(identity.get("name")) == target or
                            candidate.get("avatarHash") and candidate.get("avatarHash") in known_hashes):
                        confirmed.append(candidate)
                if len(confirmed) != 1:
                    return None
                seat = dict(confirmed[0])
                source += ":identity"
            else:
                return None
            seat["profileBindingSource"] = source
            seat["profilePrefixConfirmed"] = prefix_confirmed
            return seat

        exact = [seat for seat in seats if normalize(seat.get("name")) == target]
        matched = uniquely_bound(exact, "exact")
        if matched:
            return matched
        explicit = [seat for seat in seats
                    if self._profile_name_compatible(name, seat.get("name")) and seat not in exact]
        matched = uniquely_bound(explicit, "explicit_abbreviation")
        if matched:
            return matched
        prefixes = [seat for seat in seats
                    if 2 <= len(normalize(seat.get("name"))) < len(target) and
                    target.startswith(normalize(seat.get("name")))]
        matched = uniquely_bound(prefixes, "confirmed_ocr_prefix", prefix_confirmed=True)
        if matched:
            return matched
        raise ValueError("无法把弹窗名称唯一绑定到当前座位；请确认当前桌只有该玩家或已有头像身份记录")

    def _record_profile_statistics_capture(self, result):
        record = dict(result)
        record.update(appVersion=APP_VERSION, runtimeId=self.runtime_id, recordedAt=time.time())
        try:
            self._append_bounded_audit(self.profile_statistics_audit_file, record)
        except OSError:
            pass

    def _profile_candidate_seats(self):
        with self.state_lock:
            seats = [dict(seat) for seat in (self.cached_state or {}).get("seats", [])]
        seat_count = 6 if self.layout == "6max" else 8
        hero_index = 3 if seat_count == 6 else 4
        by_index = {seat.get("index"): seat for seat in seats}
        result = []
        for index in range(seat_count):
            if index == hero_index:
                continue
            seat = by_index.get(index, {"index": index})
            result.append({"seat": index + 1, "name": seat.get("name") or "名称未识别",
                           "empty": bool(seat.get("empty")),
                           "isHero": False})
        return result

    def _pending_profile_capture_result(self, parsed):
        queued_count = len(self.pending_profile_statistics_queue)
        return {
            "status": "needs_seat",
            "message": ("数据已自动识别，请选择对应座位" +
                        (f"；另有{queued_count}条等待确认" if queued_count else "")),
            "bindingError": parsed.get("bindingError"),
            "capturedAt": parsed["capturedAt"], "player": parsed["name"],
            "seat": None, "snapshotFile": parsed.get("snapshotFile"),
            "queuedCount": queued_count,
            "candidateSeats": self._profile_candidate_seats(),
            "statistics": {key: parsed[key] for key in (
                "levelHands", "vpipRate", "totalHands", "pfrRate",
                "rateDenominatorAssumption")},
        }

    def _activate_next_pending_profile_statistics(self):
        if self.pending_profile_statistics is None and self.pending_profile_statistics_queue:
            self.pending_profile_statistics = self.pending_profile_statistics_queue.popleft()
        if self.pending_profile_statistics is None:
            return None
        self.profile_statistics_capture = self._pending_profile_capture_result(
            self.pending_profile_statistics)
        return dict(self.profile_statistics_capture)

    def _confirm_profile_seat_name(self, index, name):
        name = str(name or "").strip()
        if not name:
            return
        self.profile_confirmed_names[index] = name
        tracker = self.seat_trackers.setdefault(index, {})
        tracker.update(name=name, pendingName=name, pendingNameFrames=2)
        with self.state_lock:
            state = dict(self.cached_state or {})
            seats = [dict(seat) for seat in state.get("seats", [])]
            seat = next((item for item in seats if item.get("index") == index), None)
            if seat is None:
                seat = {"index": index, "empty": False, "occupancy": "occupied"}
                seats.append(seat)
            seat.update(name=name, nameSource="profile_popup")
            state["seats"] = sorted(seats, key=lambda item: item.get("index", 0))
            self.cached_state = state

    def _observe_confirmed_profile_name(self, index, observed_name, tracker):
        confirmed = self.profile_confirmed_names.get(index)
        if confirmed:
            tracker.pop("profileNameConflict", None)
            tracker.pop("profileNameConflictFrames", None)
            return
        tracker.pop("profileNameConflict", None)
        tracker.pop("profileNameConflictFrames", None)

    def _confirmed_profile_seats(self):
        hero_index = 3 if self.layout == "6max" else 4
        return [{"seat": index + 1, "name": name}
                for index, name in sorted(self.profile_confirmed_names.items())
                if index != hero_index]

    def _refresh_profile_summaries(self):
        with self.state_lock:
            seats = [dict(seat) for seat in (self.cached_state or {}).get("seats", [])]
        profiles = self.history_store.summaries(seats)
        with self.state_lock:
            self.cached_state = dict(self.cached_state or {})
            self.cached_state["opponentProfiles"] = profiles

    def _schedule_profile_calibration(self):
        if not self.history_store.needs_profile_calibration():
            return
        with self.profile_calibration_lock:
            if self.profile_calibration_running:
                return
            self.profile_calibration_running = True

        def calibrate():
            try:
                output_dir = self.data_dir / "profile-calibration"
                result = subprocess.run(
                    [node_executable(), str(APP_DIR / "calibrate_v2_profiles.js"),
                     str(self.history_store.profiles_file), str(output_dir)],
                    capture_output=True, text=True, timeout=600,
                    creationflags=getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0),
                )
                if result.returncode == 0:
                    self.history_store.reload_profile_calibrations()
                    self._refresh_profile_summaries()
            except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
                pass
            finally:
                with self.profile_calibration_lock:
                    self.profile_calibration_running = False

        threading.Thread(target=calibrate, daemon=True,
                         name="profile-calibration").start()

    def _save_profile_snapshot(self, frame, captured_at):
        self.profile_statistics_snapshot_dir.mkdir(parents=True, exist_ok=True)
        path = self.profile_statistics_snapshot_dir / f"{int(captured_at * 1000)}.jpg"
        cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, 88])
        snapshots = sorted(self.profile_statistics_snapshot_dir.glob("*.jpg"))
        for old in snapshots[:-20]:
            try:
                old.unlink()
            except OSError:
                pass
        return str(path)

    def _profile_snapshot_regions(self, frame, origin):
        height, width = frame.shape[:2]
        regions = []
        with self.capture_lock:
            bbox = list(self.tracked_bbox) if self.tracked_bbox else None
        if bbox:
            left, top = origin
            x1, y1, x2, y2 = (bbox[0] - left, bbox[1] - top,
                              bbox[2] - left, bbox[3] - top)
            x1, y1, x2, y2 = (max(0, x1), max(0, y1), min(width, x2), min(height, y2))
            if x2 > x1 and y2 > y1:
                regions.append(("table", frame[y1:y2, x1:x2]))
        tile_width, tile_height = min(1100, width), min(1600, height)
        step_x, step_y = max(1, tile_width * 3 // 4), max(1, tile_height * 3 // 4)
        x_values = list(range(0, max(1, width - tile_width + 1), step_x))
        y_values = list(range(0, max(1, height - tile_height + 1), step_y))
        x_values.append(max(0, width - tile_width))
        y_values.append(max(0, height - tile_height))
        for y in dict.fromkeys(y_values):
            for x in dict.fromkeys(x_values):
                regions.append((f"desktop:{x},{y}", frame[y:y + tile_height, x:x + tile_width]))
        return regions

    def _parse_profile_snapshot(self, frame, origin):
        best_error = None
        for source, region in self._profile_snapshot_regions(frame, origin):
            items = self._ocr_items(region)
            visible = OpponentStatsParser.popup_visible(items)
            try:
                parsed = OpponentStatsParser.parse(
                    items, region.shape[1], region.shape[0], region)
                return parsed, source
            except ValueError as error:
                if visible:
                    best_error = error
        if best_error:
            raise best_error
        raise ValueError("桌面快照中未找到头像统计弹窗；请先打开对手头像资料")

    def _bind_or_queue_profile_statistics(self, parsed):
        queued = dict(parsed)
        if self.pending_profile_statistics is None:
            self.pending_profile_statistics = queued
        else:
            self.pending_profile_statistics_queue.append(queued)
        result = self._pending_profile_capture_result(self.pending_profile_statistics)
        self.profile_statistics_capture = result
        self._record_profile_statistics_capture(dict(
            self._pending_profile_capture_result(queued),
            queued=queued is not self.pending_profile_statistics))
        return dict(result)

    @staticmethod
    def _profile_statistics_payload(parsed):
        fields = (
            "levelHands", "vpipRate", "totalHands", "pfrRate",
            "threeBetRate", "cBetRate", "showdownRate", "showdownWinRate",
            "aggressionFactor", "averageBuyIn", "averageResult", "bbPer100",
        )
        return {field: parsed[field] for field in fields if parsed.get(field) is not None}

    def _is_hero_profile_statistics(self, parsed):
        hero_index = 3 if self.layout == "6max" else 4
        with self.state_lock:
            seats = list((self.cached_state or {}).get("seats", []))
        hero = next((seat for seat in seats if seat.get("index") == hero_index), {})
        name = str(parsed.get("name") or "").strip()
        return (
            name.casefold() == "zixia888" or
            self._profile_name_compatible(name, hero.get("name")) or
            self._profile_name_compatible(name, self.hero_profile.get("name"))
        )

    def _save_hero_statistics(self, parsed, source):
        statistics = self._profile_statistics_payload(parsed)
        advanced = set(OpponentStatsParser.ADVANCED_LABELS)
        self.hero_profile.update({
            "name": parsed.get("name"), "statistics": statistics,
            "capturedAt": parsed.get("capturedAt") or time.time(),
            "captureSource": source,
            "missingAdvancedFields": sorted(advanced - set(statistics)),
        })
        self._save_hero_profile()
        hero_index = 3 if self.layout == "6max" else 4
        name = str(parsed.get("name") or "").strip()
        if name:
            tracker = self.seat_trackers.setdefault(hero_index, {})
            tracker.update(name=name, pendingName=name, pendingNameFrames=2)
            with self.state_lock:
                state = dict(self.cached_state or {})
                seats = [dict(seat) for seat in state.get("seats", [])]
                seat = next((item for item in seats if item.get("index") == hero_index), None)
                if seat is None:
                    seat = {"index": hero_index, "isHero": True, "empty": False}
                    seats.append(seat)
                seat.update(name=name, nameSource="hero_profile_popup", isHero=True)
                state["seats"] = sorted(seats, key=lambda item: item.get("index", 0))
                self.cached_state = state
        result = {
            "status": "hero_ok", "message": "本人画像已更新",
            "capturedAt": self.hero_profile["capturedAt"], "player": name,
            "seat": hero_index + 1, "statistics": statistics,
            "missingAdvancedFields": self.hero_profile["missingAdvancedFields"],
            "snapshotFile": parsed.get("snapshotFile"), "profileKind": "hero",
        }
        self._record_profile_statistics_capture(result)
        return result

    def _route_profile_statistics(self, parsed, source):
        if self._is_hero_profile_statistics(parsed):
            return self._save_hero_statistics(parsed, source)
        return self._bind_or_queue_profile_statistics(parsed)

    def _capture_profile_statistics_frame(self, frame, captured_at, source="automatic_popup"):
        with self.profile_statistics_lock:
            snapshot_file = self._save_profile_snapshot(frame, captured_at)
            items = self._ocr_items(frame)
            parsed = OpponentStatsParser.parse(
                items, frame.shape[1], frame.shape[0], frame)
            parsed.update(capturedAt=captured_at, snapshotFile=snapshot_file,
                          snapshotRegion=source)
            return self._route_profile_statistics(parsed, source)

    def _automatic_profile_capture_worker(self, frame, captured_at):
        try:
            result = self._capture_profile_statistics_frame(frame, captured_at)
            self.profile_auto_capture_completed = result.get("status") in (
                "ok", "needs_seat", "hero_ok")
        except Exception as error:
            if self.profile_auto_capture_attempts >= 5:
                self.profile_statistics_capture = {
                    "status": "error", "message": f"头像弹窗自动采集失败：{error}",
                    "capturedAt": captured_at, "player": None, "seat": None,
                    "statistics": None,
                }
                self._record_profile_statistics_capture(self.profile_statistics_capture)
        finally:
            self.profile_auto_capture_inflight = False
            self.profile_auto_next_attempt_at = time.time() + .35

    def _observe_profile_scene(self, frame, captured_at, special_scene):
        if special_scene != "player_profile":
            if self.profile_scene_active:
                self.profile_scene_active = False
                self.profile_auto_capture_completed = False
                self.profile_auto_capture_attempts = 0
                self.profile_auto_next_attempt_at = 0.0
            return
        if not self.profile_scene_active:
            self.profile_scene_active = True
            self.profile_auto_capture_completed = False
            self.profile_auto_capture_attempts = 0
            self.profile_auto_next_attempt_at = 0.0
        if (self.profile_auto_capture_completed or self.profile_auto_capture_inflight or
                self.profile_auto_capture_attempts >= 5 or
                time.time() < self.profile_auto_next_attempt_at):
            return
        self.profile_auto_capture_attempts += 1
        self.profile_auto_capture_inflight = True
        threading.Thread(target=self._automatic_profile_capture_worker,
                         args=(frame.copy(), captured_at), daemon=True).start()

    def _save_bound_profile_statistics(self, seat, parsed, binding_source):
        seat = dict(seat)
        seat["profileBindingSource"] = binding_source
        saved = self.history_store.observe_platform_statistics(seat, parsed)
        self._confirm_profile_seat_name(int(seat["index"]), parsed["name"])
        self._refresh_profile_summaries()
        result = {
            "status": "ok", "message": "头像数据已采集并关联座位",
            "capturedAt": parsed["capturedAt"], "player": parsed["name"],
            "seat": int(seat["index"]) + 1, "bindingSource": binding_source,
            "snapshotFile": parsed.get("snapshotFile"),
            "statistics": {key: saved[key] for key in (
                "levelHands", "vpipRate", "totalHands", "pfrRate",
                "rateDenominatorAssumption")},
        }
        self.profile_statistics_capture = result
        self._record_profile_statistics_capture(result)
        return dict(result)

    def _resume_after_profile_popup(self, generation):
        missing_frames = 0
        deadline = time.time() + 60
        while generation == self.profile_popup_capture_generation and time.time() < deadline:
            time.sleep(.25)
            with self.capture_lock:
                bbox = list(self.tracked_bbox) if self.tracked_bbox else None
            if not bbox:
                break
            try:
                frame, _ = self.capture_layer.grab(bbox)
                visible = OpponentStatsParser.popup_visible(self._ocr_items(frame))
            except Exception:
                visible = True
            missing_frames = 0 if visible else missing_frames + 1
            if missing_frames >= 2:
                self.profile_popup_capture_active = False
                if self.recognition_requested:
                    self.recognition_active.set()
                self.profile_statistics_capture["resumeMessage"] = "弹窗已关闭，实时识别已恢复"
                if self.profile_statistics_capture.get("status") != "error":
                    self.profile_statistics_capture["message"] = "弹窗已关闭，实时识别已恢复"
                return
        if generation == self.profile_popup_capture_generation:
            self.profile_popup_capture_active = False
            timeout_message = "等待弹窗关闭超时；请关闭弹窗后重新点击采集按钮"
            if self.profile_statistics_capture.get("status") == "error":
                self.profile_statistics_capture["resumeMessage"] = timeout_message
            else:
                self.profile_statistics_capture.update(status="warning", message=timeout_message)

    def capture_opponent_statistics(self):
        if self.profile_auto_capture_inflight:
            return {"status": "pending", "message": "正在自动采集头像弹窗数据",
                    "capturedAt": None, "player": None, "seat": None,
                    "statistics": None}
        parsed = None
        snapshot_file = None
        captured_at = time.time()
        try:
            desktop, origin = capture_desktop()
            if desktop is None:
                raise ValueError("无法取得桌面快照")
            frame = cv2.cvtColor(np.asarray(desktop), cv2.COLOR_RGB2BGR)
            snapshot_file = self._save_profile_snapshot(frame, captured_at)
            parsed, snapshot_region = self._parse_profile_snapshot(frame, origin)
            parsed["capturedAt"] = captured_at
            parsed["snapshotFile"] = snapshot_file
            parsed["snapshotRegion"] = snapshot_region
            return self._route_profile_statistics(parsed, snapshot_region)
        except Exception as error:
            self.profile_statistics_capture = {
                "status": "error", "message": str(error), "capturedAt": captured_at,
                "player": parsed.get("name") if parsed else None, "seat": None,
                "snapshotFile": snapshot_file,
                "statistics": ({key: parsed[key] for key in (
                    "levelHands", "vpipRate", "totalHands", "pfrRate",
                    "rateDenominatorAssumption")} if parsed else None),
            }
            self._record_profile_statistics_capture(self.profile_statistics_capture)
            return dict(self.profile_statistics_capture)

    def capture_hero_statistics(self):
        captured_at = time.time()
        parsed = None
        snapshot_file = None
        try:
            desktop, origin = capture_desktop()
            if desktop is None:
                raise ValueError("无法取得桌面快照")
            frame = cv2.cvtColor(np.asarray(desktop), cv2.COLOR_RGB2BGR)
            snapshot_file = self._save_profile_snapshot(frame, captured_at)
            parsed, snapshot_region = self._parse_profile_snapshot(frame, origin)
            parsed.update(capturedAt=captured_at, snapshotFile=snapshot_file,
                          snapshotRegion=snapshot_region)
            return self._save_hero_statistics(parsed, snapshot_region)
        except Exception as error:
            result = {
                "status": "error", "message": str(error),
                "capturedAt": captured_at, "player": parsed.get("name") if parsed else None,
                "snapshotFile": snapshot_file, "profileKind": "hero",
            }
            self._record_profile_statistics_capture(result)
            return result

    def hero_profile_state(self):
        statistics = dict(self.hero_profile.get("statistics") or {})
        matrix = dict(self.hero_profile.get("matrix") or {})
        sample = int(statistics.get("levelHands") or 0)
        observations = []
        vpip, pfr = statistics.get("vpipRate"), statistics.get("pfrRate")
        if isinstance(vpip, (int, float)) and isinstance(pfr, (int, float)):
            gap = vpip - pfr
            if gap >= .15:
                observations.append("主动入池率明显高于加注入池率，翻牌前被动跟注或跛入可能偏多")
            elif gap >= .08:
                observations.append("主动入池与加注入池存在一定差距，需要按位置检查跟注范围")
        aggression = statistics.get("aggressionFactor")
        if isinstance(aggression, (int, float)) and aggression < 1.5:
            observations.append("激进度偏低，翻牌后可能存在过多跟注、较少主动下注的问题")
        bb100 = statistics.get("bbPer100")
        if isinstance(bb100, (int, float)) and abs(bb100) >= 50:
            observations.append("每百手结果波动异常大，当前样本不能当作长期真实盈利率")
        if sample < 1000:
            observations.append(f"当前本级别只有{sample}手，结论属于初步画像，需要继续积累分位置样本")
        if not observations:
            observations.append("汇总数据暂未显示明确异常，继续按位置积累真实起手牌与动作样本")
        dealt = sum(int(item.get("dealt") or 0)
                    for item in matrix.get("all", {}).values())
        entered = sum(int(item.get("entered") or 0)
                      for item in matrix.get("all", {}).values())
        with self.state_lock:
            current = dict(self.cached_state or {})
            decision_record = dict(self.hero_range_decision_snapshot or {})
        decision_key = decision_record.get("decisionButtonKey")
        current_runtime = current.get("runtimeId") or self.runtime_id
        current_session = current.get("tableSession", self.table_session)
        decision_matches = bool(
            decision_key and decision_record.get("street") == "preflop" and
            current_runtime == decision_record.get("runtimeId") and
            current_session == decision_record.get("tableSession") and
            current.get("handId") == decision_record.get("handId") and
            current.get("street") == "preflop")
        recorded_sequence = int(decision_record.get("actionButtonSequence") or 0)
        current_sequence = int(current.get("actionButtonSequence") or 0)
        hero_index = 3 if current.get("layout") == "6max" else 4
        hero_acted = any(
            item.get("handId") == current.get("handId") and
            item.get("street") == "preflop" and
            item.get("seat") == hero_index + 1 and
            item.get("action") not in ("blind", "post_blind", "straddle") and
            (int(item.get("actionButtonSequence") or 0) == current_sequence or
             decision_matches and not item.get("actionButtonSequence") and
             float(item.get("time") or 0) >=
             float(decision_record.get("recordedAt") or 0))
            for item in current.get("actionLog", []))
        live_decision = bool(
            current.get("street") == "preflop" and current.get("handId") and
            current.get("visualHeroTurn") and current_sequence > 0 and not hero_acted)
        formal_for_live = bool(decision_matches and recorded_sequence == current_sequence)
        decision_sequence = current_sequence if live_decision else recorded_sequence
        decision_active = live_decision
        live_cards = list(current.get("visibleHeroCards") or [])
        if len(live_cards) != 2:
            live_cards = list(current.get("heroCards") or [])
        if len(live_cards) != 2:
            live_cards = []
        hero_folded = any(
            item.get("handId") == current.get("handId") and
            item.get("seat") == hero_index + 1 and item.get("action") == "fold"
            for item in current.get("actionLog", []))
        range_mode = ("decision" if live_decision else
                      "retained" if decision_matches else "baseline")
        range_key = (
            f"decision:{current_runtime}:{current_session}:{current.get('handId')}:{decision_sequence}"
            if live_decision or decision_matches else
            f"baseline:{current_runtime}:{current_session}:{current.get('handId')}")
        retained_cards = list(decision_record.get("heroCards") or [])
        current_cards = [] if hero_folded else live_cards or retained_cards
        seats = list(current.get("seats") or [])
        hero = next((seat for seat in seats if seat.get("index") == hero_index), {})
        source = decision_record if formal_for_live or decision_matches and not live_decision else current
        big_blind = source.get("blindBig")
        hand_participants = current.get("handParticipants") or source.get("handParticipants") or []
        player_count = (len(hand_participants) if len(hand_participants) >= 2 else
                        source.get("activePlayerCount") or current.get("activePlayerCount") or 8)
        straddle_allowed = int(player_count) >= 4
        preflop_actions = [item for item in source.get("actionLog", [])
                           if item.get("handId") == source.get("handId") and
                           item.get("street") == "preflop" and
                           (straddle_allowed or item.get("action") != "straddle")]
        actions = [item for item in preflop_actions
                   if item.get("seat") != hero_index + 1]
        raise_count = source.get("preflopFullRaiseCount")
        if not isinstance(raise_count, int):
            raise_count = sum(item.get("action") in ("raise", "reraise") or
                              item.get("action") == "allin" and item.get("fullRaise") is True
                              for item in actions)
        voluntary_calls = sum(item.get("action") == "call" for item in actions)
        scenario = ("reraised" if raise_count >= 2 else
                    "raise_call" if raise_count == 1 and voluntary_calls else
                    "raised" if raise_count == 1 else
                    "limped" if voluntary_calls else "unopened")
        active = list(decision_record.get("activeOpponents") or []) if source is decision_record else []
        if not active:
            active = [seat for seat in seats if seat.get("index") != hero_index and
                      not seat.get("empty") and seat.get("action") != "fold"]
        hero_chips = hero.get("chips")
        effective = [float(item.get("amount")) for item in
                     decision_record.get("pairwiseEffective", [])
                     if source is decision_record and isinstance(item.get("amount"), (int, float))]
        if not effective:
            effective = [min(float(hero_chips), float(seat["chips"])) for seat in active
                         if isinstance(hero_chips, (int, float)) and
                         isinstance(seat.get("chips"), (int, float))]
        if not effective and isinstance(hero_chips, (int, float)) and hero_chips > 0:
            effective = [float(hero_chips)]
        effective_bb = (max(effective) / float(big_blind)
                        if effective and isinstance(big_blind, (int, float)) and big_blind > 0
                        else None)
        straddle_events = [item for item in preflop_actions
                           if item.get("action") == "straddle"]
        straddle_amounts = [float(item["amount"]) for item in straddle_events
                            if isinstance(item.get("amount"), (int, float)) and
                            item["amount"] > 0]
        detected_straddle = bool(straddle_allowed and (straddle_events or
                                 isinstance(source.get("blindStraddle"), (int, float)) and
                                 source.get("blindStraddle") > 0))
        straddle_amount = (float(source.get("blindStraddle"))
                           if isinstance(source.get("blindStraddle"), (int, float)) and
                           source.get("blindStraddle") > 0 else
                           max(straddle_amounts, default=0.0))
        range_ready = bool(
            current.get("street") == "preflop" and current.get("handId") and
            source.get("heroPosition") not in (None, "unknown") and
            isinstance(big_blind, (int, float)) and big_blind > 0 and
            (not detected_straddle or straddle_amount > 0) and effective)
        scenario_baseline = (source.get("scenarioBaseline")
                             if isinstance(source.get("scenarioBaseline"), dict)
                             else current.get("scenarioBaseline"))
        if (not isinstance(scenario_baseline, dict) or
                not scenario_baseline.get("rangeActions")):
            current_baseline = current.get("scenarioBaseline")
            if (isinstance(current_baseline, dict) and
                    (current_baseline.get("rangeActions") or
                     current_baseline.get("normalizedState"))):
                scenario_baseline = current_baseline
        if (current.get("street") == "preflop" and
                (not isinstance(scenario_baseline, dict) or
                 not scenario_baseline.get("rangeActions"))):
            try:
                display_baseline = evaluate_preflop_shadow(
                    current, hero_index, include_range=True,
                    require_actionable=False)
                if display_baseline.get("rangeActions"):
                    scenario_baseline = display_baseline
            except Exception:
                pass
        if not isinstance(scenario_baseline, dict) and current.get("street") == "preflop":
            try:
                scenario_baseline = evaluate_preflop_shadow(
                    current, hero_index, include_range=True)
            except Exception:
                scenario_baseline = None
        elif (isinstance(scenario_baseline, dict) and
              not scenario_baseline.get("rangeActions") and
              isinstance(scenario_baseline.get("normalizedState"), dict)):
            static_range = preflop_baseline_range(
                scenario_baseline["normalizedState"])
            scenario_baseline = {
                **scenario_baseline,
                "rangeActions": static_range["actions"],
                "rangeReasons": static_range["reasons"],
                "rangeRequiresRealtimeMath": static_range["requiresRealtimeMath"],
                "rangeEvidenceLevels": static_range["evidenceLevels"],
                "rangeEvidenceSources": static_range["evidenceSources"],
                "rangeClasses": static_range["classes"],
                "rangeSource": static_range["source"],
            }
        if (source is decision_record and
                (not isinstance(scenario_baseline, dict) or
                 not scenario_baseline.get("rangeActions")) and
                decision_record.get("rangeActions")):
            scenario_baseline = {
                "rangeActions": decision_record.get("rangeActions"),
                "rangeReasons": decision_record.get("rangeReasons") or {},
                "rangeSource": "场景基础策略静态范围",
            }
        range_cards = (list(decision_record.get("heroCards") or [])
                       if source is decision_record else live_cards)
        big_blind_amount = (float(big_blind)
                            if isinstance(big_blind, (int, float)) and big_blind > 0 else 0.0)
        live = straddle_amount if detected_straddle else big_blind_amount
        position = source.get("heroPosition")
        forced_posted = (live if position == "straddle" else big_blind_amount
                         if position == "big_blind" else float(source.get("blindSmall") or 0)
                         if position == "small_blind" else 0.0)
        money_actions = {"blind", "post_blind", "straddle", "call", "bet",
                         "raise", "reraise", "allin"}
        hero_invested = max(
            [forced_posted] + [float(item["amount"]) for item in preflop_actions
                               if item.get("seat") == hero_index + 1 and
                               item.get("action") in money_actions and
                               isinstance(item.get("amount"), (int, float))])
        official_call = source.get("callAmount")
        call = (float(official_call)
                if (live_decision or decision_matches) and
                isinstance(official_call, (int, float)) else
                max(0.0, live - hero_invested))
        current_price = round(max(
            [live, hero_invested + call] +
            [float(item["amount"]) for item in actions
             if item.get("action") in money_actions and
             isinstance(item.get("amount"), (int, float))]), 6)
        free_check = call <= 1e-9
        effective_straddle = straddle_amount if detected_straddle else None
        if detected_straddle and position == "straddle" and scenario == "unopened":
            scenario = "limped"
        forced_pot = sum(float(value or 0) for value in (
            source.get("blindSmall"), source.get("blindBig"), effective_straddle))
        forced_pot += float(source.get("blindAnte") or 0) * int(player_count)
        range_pot = (source.get("pot") if source is decision_record or live_decision else
                     forced_pot if forced_pot > 0 else source.get("pot"))
        minimum_raise = source.get("minRaiseTo")
        minimum_raise = (
            (float(minimum_raise) if source is decision_record else
             max(0.0, float(minimum_raise) - hero_invested))
            if isinstance(minimum_raise, (int, float)) else
            max(0.0, 2 * live - hero_invested)
        )
        return {
            "version": APP_VERSION, "name": self.hero_profile.get("name"),
            "capturedAt": self.hero_profile.get("capturedAt"),
            "statistics": statistics, "missingAdvancedFields": list(
                self.hero_profile.get("missingAdvancedFields") or []),
            "matrix": matrix, "observations": observations,
            "strategyLeaks": self._hero_strategy_leaks(),
            "currentHeroCards": current_cards,
            "currentHandClass": self._starting_hand_class(current_cards),
            "rangeDecision": ({
                "available": True,
                "active": decision_active,
                "mode": range_mode,
                "rangeKey": range_key,
                "highlightHand": bool(
                    not hero_folded and range_cards and
                    (range_mode == "baseline" or decision_active)),
                "decisionButtonKey": decision_key,
                "actionButtonSequence": decision_sequence,
                "handId": decision_record.get("handId"),
                "street": decision_record.get("street"),
                "heroCards": range_cards,
                "currentHandClass": self._starting_hand_class(range_cards),
                "officialAction": (decision_record.get("primary")
                                   if formal_for_live or range_mode == "retained" else None),
                "position": position,
                "scenario": scenario,
                "pot": range_pot,
                "call": call,
                "effective": max(effective) if effective else None,
                "players": player_count,
                "raiseCount": raise_count,
                "minRaiseTo": minimum_raise,
                "rakeRate": source.get("rakeRate"),
                "rakeCap": source.get("rakeCap"),
                "straddle": effective_straddle,
                "live": live,
                "posted": hero_invested,
                "currentPrice": current_price,
                "freeCheck": free_check,
                "smallBlind": float(source.get("blindSmall") or 0),
                "rangeTypes": [item.get("range") or "medium" for item in active],
                "legalCandidates": (list(decision_record.get("legalCandidates") or [])
                                    if source is decision_record else []),
                "rangeActions": (dict(scenario_baseline.get("rangeActions") or {})
                                  if isinstance(scenario_baseline, dict) else {}),
                "rangeReasons": (dict(scenario_baseline.get("rangeReasons") or {})
                                  if isinstance(scenario_baseline, dict) else {}),
                "rangeRequiresRealtimeMath": (
                    dict(scenario_baseline.get("rangeRequiresRealtimeMath") or {})
                    if isinstance(scenario_baseline, dict) else {}),
                "rangeEvidenceLevels": (
                    dict(scenario_baseline.get("rangeEvidenceLevels") or {})
                    if isinstance(scenario_baseline, dict) else {}),
                "rangeEvidenceSources": (
                    dict(scenario_baseline.get("rangeEvidenceSources") or {})
                    if isinstance(scenario_baseline, dict) else {}),
                "rangeSource": (scenario_baseline.get("rangeSource")
                                 if isinstance(scenario_baseline, dict) else None),
                "rangeContext": (dict(scenario_baseline.get("normalizedState") or {})
                                 if isinstance(scenario_baseline, dict) else {}),
            } if range_ready else None),
            "rangeCollectionActive": self.hero_profile.get(
                "rangeCollectionActive", True) is not False,
            "rangeCollectionStartedAt": self.hero_profile.get("rangeCollectionStartedAt"),
            "windowTopmost": self.hero_profile_topmost,
            "matrixSummary": {"classes": 169, "combinations": 1326,
                              "observedDeals": dealt, "enteredHands": entered},
            "rangeDefaults": {
                "position": source.get("heroPosition", "dealer"),
                "scenario": scenario,
                "smallBlind": source.get("blindSmall"),
                "bigBlind": big_blind,
                "straddle": effective_straddle,
                "ante": source.get("blindAnte"),
                "rakeRate": source.get("rakeRate"),
                "rakeCapBb": (float(source["rakeCap"]) / float(big_blind)
                              if isinstance(source.get("rakeCap"), (int, float)) and
                              isinstance(big_blind, (int, float)) and big_blind > 0 else None),
                "effectiveBb": effective_bb,
                "players": player_count,
                "baselineState": (dict(scenario_baseline.get("normalizedState") or {})
                                  if isinstance(scenario_baseline, dict) else {}),
                "live": source.get("heroPosition") not in (None, "unknown") and
                        isinstance(big_blind, (int, float)) and big_blind > 0,
            },
        }

    @staticmethod
    def preflop_baseline_catalog(players=8, position=None):
        try:
            players = int(players)
        except (TypeError, ValueError):
            players = 8
        players = max(2, min(8, players))
        positions = PREFLOP_POSITIONS_BY_PLAYERS[players]
        position = position if position in positions else positions[0]
        scenes = []
        for index, scene in enumerate(preflop_legal_scenario_families(players, position)):
            for pressure in PREFLOP_ACTION_PRESSURE[scene["family"]]:
                scenes.append({
                    "key": f"{index}:{pressure}", "family": scene["family"],
                    "heroRole": scene["heroRole"],
                    "actors": list(scene["actors"]), "pressureBucket": pressure,
                })
        return {
            "players": players, "position": position,
            "positions": list(positions), "scenes": scenes,
            "stackBuckets": list(PREFLOP_STACK_BUCKETS),
            "rakePolicies": list(PREFLOP_RAKE_POLICIES),
        }

    @staticmethod
    def preflop_baseline_range_table(request):
        request = request if isinstance(request, dict) else {}
        catalog = Api.preflop_baseline_catalog(
            request.get("players", 8), request.get("position"))
        scenes = {scene["key"]: scene for scene in catalog["scenes"]}
        scene = scenes.get(str(request.get("sceneKey")))
        if scene is None:
            return {"valid": False, "reason": "当前人数与位置没有这个合法场景",
                    "catalog": catalog}
        stack = request.get("stackBucket")
        rake = request.get("rakePolicy")
        if stack not in PREFLOP_STACK_BUCKETS:
            return {"valid": False, "reason": "有效筹码档位无效", "catalog": catalog}
        if rake not in PREFLOP_RAKE_POLICIES:
            return {"valid": False, "reason": "抽成档位无效", "catalog": catalog}
        normalized = {
            "activePlayers": catalog["players"],
            "heroPosition": catalog["position"],
            "effectiveStackBucket": stack, "rakePolicy": rake,
            "priorActionPattern": scene["family"],
            "pressureBucket": scene["pressureBucket"],
            "actors": tuple(scene["actors"]), "heroRole": scene["heroRole"],
        }
        result = preflop_baseline_range(normalized)
        return {
            "valid": result["classes"] == 169, "classes": result["classes"],
            "actions": result["actions"], "reasons": result["reasons"],
            "requiresRealtimeMath": result["requiresRealtimeMath"],
            "evidenceLevels": result["evidenceLevels"],
            "evidenceSources": result["evidenceSources"],
            "source": result["source"], "scenario": scene,
            "players": catalog["players"], "position": catalog["position"],
            "stackBucket": stack, "rakePolicy": rake,
        }

    def clear_hero_range_statistics(self):
        self.hero_profile["matrix"] = {}
        self.hero_profile["rangeCollectionActive"] = False
        self.hero_profile["rangeCollectionStartedAt"] = None
        self.hero_profile["historyBackfillVersion"] = 1
        self.hero_profile["historyBackfillHands"] = 0
        self.hero_range_seen.clear()
        self._save_hero_profile()
        return {"cleared": True, "active": False, "status": "本人实际入池范围已清空，统计已停止"}

    def clear_hero_strategy_comparisons(self):
        self.hero_profile["strategyComparisons"] = []
        self.pending_hero_decisions.clear()
        self._save_hero_profile()
        return {"cleared": True, "status": "本人策略对照样本已清空"}

    def set_hero_range_collection(self, active):
        active = bool(active)
        self.hero_profile["rangeCollectionActive"] = active
        if active:
            self.hero_profile["rangeCollectionStartedAt"] = time.time()
        self._save_hero_profile()
        return {
            "active": active,
            "status": "本人实际入池范围已开始统计" if active else "本人实际入池范围已暂停统计",
        }

    @staticmethod
    def _primary_work_area():
        monitors = []
        callback_type = ctypes.WINFUNCTYPE(
            ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p,
            ctypes.POINTER(ctypes.wintypes.RECT), ctypes.c_ssize_t)

        class MonitorInfo(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.wintypes.DWORD),
                ("rcMonitor", ctypes.wintypes.RECT),
                ("rcWork", ctypes.wintypes.RECT),
                ("dwFlags", ctypes.wintypes.DWORD),
            ]

        @callback_type
        def callback(monitor_handle, _, rect, __):
            info = MonitorInfo()
            info.cbSize = ctypes.sizeof(info)
            if user32.GetMonitorInfoW(monitor_handle, ctypes.byref(info)):
                work = info.rcWork
                monitors.append((work.left, work.top, work.right, work.bottom, info.dwFlags))
            return True

        user32.EnumDisplayMonitors(None, None, callback, 0)
        primary = next((item for item in monitors if item[4] & 1), None)
        if primary:
            return primary[:4]
        return (0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))

    def _position_auxiliary_window(self, panel):
        window = self.hero_profile_window if panel == "hero" else self.opponent_hands_window
        if window is None:
            return None
        left, top, right, bottom = self._primary_work_area()
        split = left + (right - left) // 2
        x = left if panel == "hero" else split
        width = split - left if panel == "hero" else right - split
        height = bottom - top
        title = "My Poker Ranges" if panel == "hero" else "Opponent Range Statistics"
        hwnd = self._window_hwnd(title)
        if hwnd:
            user32.SetWindowPos(hwnd, 0, x, top, width, height, 0x0010 | 0x0004)
        else:
            try:
                dpi = user32.GetDpiForSystem() if hasattr(user32, "GetDpiForSystem") else 96
                scale = 96 / max(96, dpi)
                window.resize(round(width * scale), round(height * scale))
                window.move(round(x * scale), round(top * scale))
            except Exception:
                pass
        return [x, top, width, height]

    def show_hero_profile_window(self):
        if self.hero_profile_window is None:
            return {"visible": False, "status": "本人画像窗口尚未创建"}
        self._position_auxiliary_window("hero")
        self.hero_profile_window.show()
        self.hero_profile_visible = True
        self._notify_auxiliary_visibility("hero", True)
        self._position_auxiliary_window("hero")
        hwnd = self._window_hwnd("My Poker Ranges")
        if hwnd:
            self._apply_topmost(hwnd, self.hero_profile_topmost)
        return {"visible": True, "status": "本人画像已打开"}

    def hide_hero_profile_window(self):
        if self.shutting_down:
            return {"visible": False}
        if self.hero_profile_window is not None:
            self.hero_profile_window.hide()
        self.hero_profile_visible = False
        self._notify_auxiliary_visibility("hero", False)
        return {"visible": False}

    def toggle_hero_profile_window(self):
        if self.hero_profile_visible:
            return self.hide_hero_profile_window()
        return self.show_hero_profile_window()

    def on_hero_profile_closing(self):
        if self.shutting_down:
            return None
        return self._cancel_auxiliary_close("hero")

    def show_opponent_hands_window(self):
        if self.opponent_hands_window is None:
            return {"visible": False, "status": "对手范围统计窗口尚未创建"}
        self._position_auxiliary_window("opponent")
        self.opponent_hands_window.show()
        self.opponent_hands_visible = True
        self._notify_auxiliary_visibility("opponent", True)
        self._position_auxiliary_window("opponent")
        hwnd = self._window_hwnd("Opponent Range Statistics")
        if hwnd:
            self._apply_topmost(hwnd, self.opponent_hands_topmost)
        return {"visible": True, "status": "对手范围统计已打开"}

    def hide_opponent_hands_window(self):
        if self.shutting_down:
            return {"visible": False}
        if self.opponent_hands_window is not None:
            self.opponent_hands_window.hide()
        self.opponent_hands_visible = False
        self._notify_auxiliary_visibility("opponent", False)
        return {"visible": False}

    def toggle_opponent_hands_window(self):
        if self.opponent_hands_visible:
            return self.hide_opponent_hands_window()
        return self.show_opponent_hands_window()

    def on_opponent_hands_closing(self):
        if self.shutting_down:
            return None
        return self._cancel_auxiliary_close("opponent")

    def _cancel_auxiliary_close(self, panel):
        window = self.hero_profile_window if panel == "hero" else self.opponent_hands_window
        title = "My Poker Ranges" if panel == "hero" else "Opponent Range Statistics"
        if panel == "hero":
            self.hero_profile_visible = False
        else:
            self.opponent_hands_visible = False
        hwnd = self._window_hwnd(title)
        if hwnd:
            user32.ShowWindow(hwnd, 0)
        elif window is not None:
            threading.Thread(target=window.hide, daemon=True).start()
        threading.Thread(
            target=self._notify_auxiliary_visibility,
            args=(panel, False), daemon=True).start()
        return False

    def set_auxiliary_window_topmost(self, panel, topmost):
        if panel not in ("hero", "opponent"):
            return {"topmost": False, "status": "未知面板"}
        topmost = bool(topmost)
        title = "My Poker Ranges" if panel == "hero" else "Opponent Range Statistics"
        if panel == "hero":
            self.hero_profile_topmost = topmost
        else:
            self.opponent_hands_topmost = topmost
        hwnd = self._window_hwnd(title)
        if hwnd:
            self._apply_topmost(hwnd, topmost)
        name = "我的范围" if panel == "hero" else "对手范围"
        return {"topmost": topmost,
                "status": f"{name}面板已置顶" if topmost else f"{name}面板已取消置顶"}

    def _notify_auxiliary_visibility(self, panel, visible):
        if self.window is None:
            return
        try:
            self.window.evaluate_js(
                f"window.__setAuxiliaryVisibility && window.__setAuxiliaryVisibility("
                f"{json.dumps(panel)}, {str(bool(visible)).lower()})")
        except Exception:
            pass

    def record_deep_analysis(self, sample):
        if not isinstance(sample, dict):
            return {"recorded": False}
        record = dict(sample)
        record.setdefault("strategyMode", self.strategy_mode)
        record.update(appVersion=APP_VERSION, runtimeId=self.runtime_id,
                      recordedAt=time.time())
        result = record.get("result")
        if isinstance(result, dict):
            compact_result = dict(result)
            compact_result["evaluated"] = [
                {key: item.get(key) for key in
                 ("kind", "action", "amount", "scene", "ev", "evLow", "evHigh",
                  "eligible", "solveTier", "reason") if key in item}
                for item in result.get("evaluated", []) if isinstance(item, dict)
            ]
            for key in ("best", "rawBest"):
                item = result.get(key)
                if isinstance(item, dict):
                    compact_result[key] = {
                        field: item.get(field) for field in
                        ("kind", "action", "amount", "scene", "ev", "evLow", "evHigh",
                         "eligible", "solveTier") if field in item}
            record["result"] = compact_result
        with self.state_lock:
            current = dict(self.deep_analysis or {})
            same_decision = (current.get("latest") or {}).get("decisionButtonKey") == record.get("decisionButtonKey")
            stages = dict(current.get("stages") or {}) if same_decision else {}
            if record.get("stage") in ("T2", "T3"):
                stages[record["stage"]] = record
            confirmation = self._deep_confirmation(stages)
            self.deep_analysis = {"latest": record, "stages": stages,
                                  "confirmation": confirmation}
        self._rotate_log_if_needed(
            self.deep_analysis_file, self.audit_log_max_bytes,
            self.audit_log_backup_count)
        with self.deep_analysis_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return {"recorded": True, "stage": record.get("stage")}

    @staticmethod
    def _deep_action_family(kind):
        if kind == "fold":
            return "fold"
        if kind == "check":
            return "check"
        if kind in ("call", "allin_call"):
            return "call"
        if kind in ("quick_bet", "custom_raise", "minimum_raise", "allin"):
            return "raise"
        return kind

    @classmethod
    def _deep_confirmation(cls, stages):
        t2, t3 = stages.get("T2"), stages.get("T3")
        if not t2 or not t3:
            return {"status": "pending", "eligible": False,
                    "reason": "等待T2和T3两层都完成"}
        reference = t3.get("t1Reference") or t2.get("t1Reference") or {}
        results = [t2.get("result") or {}, t3.get("result") or {}]
        best = [result.get("best") or {} for result in results]
        kinds = [reference.get("kind"), best[0].get("kind"), best[1].get("kind")]
        families = [cls._deep_action_family(kind) for kind in kinds]
        action_matches = bool(families[0] and len(set(families)) == 1)
        amounts = [reference.get("amount"), best[0].get("amount"), best[1].get("amount")]
        numeric_amounts = [float(value) for value in amounts
                           if isinstance(value, (int, float))]
        tolerance = max(.01, abs(float(reference.get("amount") or 0)) * .02)
        amount_matches = (families[0] != "raise" or len(numeric_amounts) == 3 and
                          max(numeric_amounts) - min(numeric_amounts) <= tolerance)
        complete = all(result.get("complete") is True for result in results)
        target_met = all((result.get("audit") or {}).get("targetMet") is True
                         for result in results)
        risk_clear = all(item.get("selectionEligible") is not False and
                         not item.get("riskGateReason") for item in best)
        eligible = action_matches and amount_matches and complete and target_met and risk_clear
        failed = []
        for passed, reason in ((action_matches, "动作不一致"),
                               (amount_matches, "金额不一致"),
                               (complete, "求解未完成"),
                               (target_met, "误差目标未达到"),
                               (risk_clear, "风险门未通过")):
            if not passed:
                failed.append(reason)
        return {"status": "confirmed" if eligible else "rejected",
                "eligible": eligible, "applied": False,
                "mode": "confirm_only", "actionFamily": families[0],
                "amount": numeric_amounts[0] if numeric_amounts else None,
                "tolerance": tolerance, "reason": "、".join(failed) or "T1/T2/T3一致确认"}

    def deep_analysis_state(self):
        with self.state_lock:
            return dict(self.deep_analysis)

    def assign_opponent_statistics_seat(self, seat_number, confirmed_name=None):
        parsed = dict(self.pending_profile_statistics or {})
        confirmed_name = str(confirmed_name or "").strip()
        if not parsed and not confirmed_name:
            return {"status": "error", "message": "没有等待匹配的头像快照数据"}
        try:
            index = int(seat_number) - 1
        except (TypeError, ValueError):
            return {"status": "error", "message": "座位号无效"}
        candidates = {item["seat"] for item in self._profile_candidate_seats()}
        if index + 1 not in candidates:
            return {"status": "error", "message": "本人座位由我的范围面板自动识别，不能人工绑定"}
        with self.state_lock:
            seats = [dict(seat) for seat in (self.cached_state or {}).get("seats", [])]
        seat = next((seat for seat in seats if seat.get("index") == index), {"index": index})
        if confirmed_name:
            parsed["name"] = confirmed_name
        name = str(parsed.get("name") or "").strip()
        if not name:
            return {"status": "error", "message": "请先填写确认后的玩家姓名"}
        hero_index = 3 if self.layout == "6max" else 4
        if seat.get("isHero") or index == hero_index or not parsed.get("statistics") and not all(
                key in parsed for key in ("levelHands", "vpipRate", "totalHands", "pfrRate")):
            self._confirm_profile_seat_name(index, name)
            self._refresh_profile_summaries()
            result = {
                "status": "ok", "message": "玩家姓名已人工确认",
                "capturedAt": parsed.get("capturedAt") or time.time(),
                "player": name, "seat": index + 1, "bindingSource": "manual_name",
                "snapshotFile": parsed.get("snapshotFile"), "statistics": None,
            }
            self.profile_statistics_capture = result
            self._record_profile_statistics_capture(result)
            if parsed:
                self.pending_profile_statistics = None
                return self._activate_next_pending_profile_statistics() or result
            return result
        seat["profileManualConfirmed"] = True
        normalized = self.history_store._normalized_name(seat.get("name"))
        full_name = self.history_store._normalized_name(parsed.get("name"))
        if 2 <= len(normalized) < len(full_name) and full_name.startswith(normalized):
            seat["profilePrefixConfirmed"] = True
        result = self._save_bound_profile_statistics(seat, parsed, "manual_seat")
        self.pending_profile_statistics = None
        return self._activate_next_pending_profile_statistics() or result

    def show_next_profile_statistics(self):
        skipped = self.pending_profile_statistics
        if skipped is None:
            return dict(self.profile_statistics_capture)
        self._record_profile_statistics_capture({
            "status": "skipped", "message": "人工跳过本条识别结果",
            "capturedAt": skipped.get("capturedAt"), "player": skipped.get("name"),
            "seat": None, "snapshotFile": skipped.get("snapshotFile"),
        })
        self.pending_profile_statistics = None
        next_result = self._activate_next_pending_profile_statistics()
        if next_result:
            return next_result
        self.profile_statistics_capture = {
            "status": "idle", "message": "当前没有下一条；重新打开弹窗后会继续排队",
            "capturedAt": None, "player": None, "seat": None, "statistics": None,
            "queuedCount": 0,
        }
        return dict(self.profile_statistics_capture)

    def set_strategy_mode(self, mode):
        if mode not in {"auto", "strict_exploit"}:
            return {"changed": False, "mode": self.strategy_mode,
                    "status": "未知策略模式，未修改"}
        changed = mode != self.strategy_mode
        self.strategy_mode = mode
        self.config["strategyMode"] = mode
        CONFIG_FILE.write_text(
            json.dumps(self.config, ensure_ascii=False, indent=2), encoding="utf-8")
        labels = {"auto": "自动基础与剥削策略", "strict_exploit": "严格条件剥削策略"}
        return {"changed": changed, "mode": mode,
                "status": f"当前使用：{labels[mode]}"}

    def _start_recognition_workers(self):
        self.pipeline_runtime.start()

    @staticmethod
    def _ocr_warmup_image():
        return np.zeros((32, 128, 3), dtype=np.uint8)

    def _mark_ocr_worker_ready(self, channel):
        if channel == "action":
            with self._action_ocr_ready_lock:
                self._action_ocr_ready_count += 1
                if self._action_ocr_ready_count >= self._action_ocr_worker_target:
                    self.action_ocr_ready.set()
            return
        with self._avatar_ocr_ready_lock:
            self._avatar_ocr_ready_count += 1
            if self._avatar_ocr_ready_count >= self._avatar_ocr_worker_target:
                self.avatar_ocr_ready.set()

    def _wait_for_ocr_ready(self, timeout):
        if self._action_ocr_worker_target:
            self.action_ocr_ready.wait(timeout)
        if self._avatar_ocr_worker_target:
            self.avatar_ocr_ready.wait(timeout)

    def _fast_frame_loop(self):
        while True:
            if not self.recognition_active.wait(.1):
                continue
            started = time.time()
            try:
                with self.capture_lock:
                    bbox = list(self.tracked_bbox) if self.tracked_bbox else None
                if bbox:
                    frame, captured_at = self.capture_layer.grab(bbox)
                    with self.capture_lock:
                        self.latest_table_frame = frame
                        self.latest_capture_bbox = bbox
                        self.latest_frame_captured_at = captured_at
                        self.latest_frame_sequence += 1
                        sequence = self.latest_frame_sequence
                        self.latest_frame_video_second = getattr(self, "recording_second", None)
                        self.latest_frame_context = self._new_capture_context(
                            captured_at, sequence, self.latest_frame_video_second)
                        self.frame_received_at[sequence] = captured_at
                        if len(self.frame_received_at) > 600:
                            del self.frame_received_at[next(iter(self.frame_received_at))]
                    self._drain_peek_results()
                    self._observe_peek_slot(frame, captured_at, sequence)
                    self._observe_missing_hero_cards_fast(frame, captured_at, sequence)
                    try:
                        self.frame_buffer_queue.put_nowait((sequence, captured_at, bbox, frame))
                    except queue.Full:
                        self.frame_buffer_dropped += 1
            except Exception as error:
                self.fields.commit("frameChannel", str(error), 0, "capture", False)
            time.sleep(max(0.005, .03 - (time.time() - started)))

    def _observe_missing_hero_cards_fast(self, frame, captured_at, frame_sequence):
        if len(self.card_published.get("heroCards", [])) == 2:
            return False
        height, width = frame.shape[:2]
        box = self._reviewed_slot_box((315, 1570, 575, 1745), width, height)
        cards = self._recognize_cards_fast(
            frame[box[1]:box[3], box[0]:box[2]])[:2]
        if len(cards) != 2:
            return False
        return self._commit_card_observation(
            "heroCards", cards, captured_at,
            frame_sequence=frame_sequence, hand_id=self.hand_state.get("id", 0))

    def _frame_buffer_loop(self):
        while True:
            sequence, captured_at, bbox, frame = self.frame_buffer_queue.get()
            try:
                item = self.capture_layer.encode(sequence, captured_at, bbox, frame)
                if item is None:
                    continue
                with self.frame_buffer_lock:
                    self.capture_layer.buffer_seconds = self.frame_buffer_seconds
                    self.capture_layer.append(self.frame_buffer, item)
            finally:
                self.frame_buffer_queue.task_done()

    def _action_ocr_loop(self):
        worker_ocr = RapidOCR(intra_op_num_threads=1, inter_op_num_threads=1)
        ocr_cache = {}

        try:
            warmup = self._ocr_warmup_image()
            worker_ocr(warmup, use_det=False, use_cls=False, use_rec=True)
            worker_ocr(warmup)
        except Exception as error:
            self.ocr_warmup_errors.append({"channel": "action", "error": str(error)})
        finally:
            self._mark_ocr_worker_ready("action")

        def cached_line(image, mode, detected=False):
            key = (mode, image.shape, hashlib.blake2b(image, digest_size=8).digest())
            if key in ocr_cache:
                return ocr_cache[key]
            result, _ = worker_ocr(image, **({} if detected else {"use_det": False, "use_cls": False, "use_rec": True}))
            if not result:
                value = ("", 0.0)
            elif detected:
                value = (" ".join(str(item[1]) for item in result), min(float(item[2]) for item in result))
            else:
                value = (str(result[0][0]), float(result[0][1]))
            if len(ocr_cache) >= 512:
                ocr_cache.pop(next(iter(ocr_cache)))
            ocr_cache[key] = value
            return value

        def ocr_line(image):
            return cached_line(image, "line")

        def ocr_detected_line(image):
            return cached_line(image, "detected", detected=True)
            result, _ = worker_ocr(image)
            if not result:
                return "", 0.0
            text = " ".join(str(item[1]) for item in result)
            money_confidences = [float(item[2]) for item in result
                                 if any(symbol in str(item[1]) for symbol in ("$", "¥", "￥"))]
            confidence = max(money_confidences) if money_confidences else min(float(item[2]) for item in result)
            return text, confidence

        while True:
            _, _, job = self.action_ocr_queue.get()
            try:
                job["ocrStartedAt"] = time.time()
                action_stage_started = time.time()
                crops = job.pop("crops", None)
                if crops is None:
                    crops = [job.pop("crop")]
                avatar = job.pop("avatar")
                investment = job.pop("investment", None)
                stack_image = job.pop("stack", None)
                recognized = []
                explicit_text = False
                color_action = job.get("colorAction")
                forced_action = job.get("forcedAction")
                if forced_action in ("blind", "straddle") and job.get("forcedAmount") not in (None, 0):
                    action, text, confidence = forced_action, f"known_{forced_action}", 1.0
                elif (job.get("capsuleDetected") and color_action == "call" and
                      job.get("knownCallAmount") not in (None, 0)):
                    action, text, confidence = "call", "color_call+rule_amount", float(
                        max(.9, job.get("capsuleColorConfidence") or 0))
                elif (job.get("capsuleDetected") and color_action == "check" and
                      not job.get("forcedStraddleWindow") and
                      not job.get("forceActionTextOcr")):
                    action, text, confidence = "check", "color_check", float(
                        job.get("capsuleColorConfidence") or .9)
                elif job.get("capsuleDetected") and color_action == "investment":
                    action, text, confidence = "raise", "color_investment", float(
                        job.get("capsuleColorConfidence") or .9)
                else:
                    for crop_entry in reversed(crops):
                        crop_capture = crop_entry if isinstance(crop_entry, dict) else None
                        crop = crop_capture.get("image") if crop_capture else crop_entry
                        height, width = crop.shape[:2]
                        text_crop = crop[int(height * .08):int(height * .86),
                                         int(width * .03):int(width * .72)]
                        if self.action_slot_classifier is not None:
                            classified, text, confidence, _ = self.action_slot_classifier.classify(
                                text_crop, ocr_line)
                        else:
                            classified = None
                            text, confidence = ocr_line(
                                cv2.resize(text_crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC))
                        text_action = next((kind for kind, words in ACTION_TEXT_WORDS.items()
                                            if any(word.lower() in text.lower() for word in words)), "waiting")
                        action = text_action if text_action != "waiting" else classified or "waiting"
                        explicit_text = text_action != "waiting"
                        if job.get("capsuleDetected") and not explicit_text:
                            detected_text, detected_confidence = ocr_detected_line(
                                cv2.resize(text_crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC))
                            detected_action = next((kind for kind, words in ACTION_TEXT_WORDS.items()
                                                    if any(word.lower() in detected_text.lower()
                                                           for word in words)), "waiting")
                            if detected_action != "waiting" and detected_confidence >= .65:
                                action, text, confidence = detected_action, detected_text, detected_confidence
                                explicit_text = True
                        recognized.append((explicit_text, action != "waiting", float(confidence or 0),
                                           action, text, crop_capture))
                        if explicit_text:
                            break
                    selected = (next((item for item in recognized if item[0]), None) or
                                max(recognized, key=lambda item: (item[1], item[2])))
                    explicit_text, _, confidence, action, text, selected_capture = selected
                    if selected_capture:
                        avatar = selected_capture.get("avatar", avatar)
                        investment = selected_capture.get("investment", investment)
                        stack_image = selected_capture.get("stack", stack_image)
                        job["selectedCropCapture"] = {
                            key: selected_capture.get(key) for key in (
                                "runtimeId", "tableSession", "handId", "street", "observedAt",
                                "frameSequence", "videoSecond"
                            )
                        }
                    if action == "waiting" and job.get("capsuleDetected") and color_action == "call":
                        action, text, confidence = "call", "color_call", float(
                            job.get("capsuleColorConfidence") or .9)
                    elif (action == "waiting" and job.get("capsuleDetected") and
                          color_action == "check" and "让" in text):
                        action, confidence = "check", max(float(confidence or 0), .8)
                job["actionTextOcrMs"] = round(max(0, time.time() - action_stage_started) * 1000, 1)
                job["explicitActionText"] = bool(explicit_text)
                avatar_text, avatar_confidence = "", 0.0
                avatar_state = "unknown"
                avatar_stage_started = time.time()
                forced_seat_validation = bool(job.get("forcedSeatValidation"))
                if ((forced_seat_validation or
                     (action != "blind" and job.get("triggerSource") != "forced_bet_scan" and
                      job.get("avatarStateCandidate") and not job.get("capsuleDetected"))) and
                        self.avatar_state_classifier is not None):
                    if job.get("expectedActionProbe") or job.get("chainGapProbe"):
                        avatar_state, classified_text, classified_confidence = (
                            self.avatar_state_classifier.classify_line(avatar, worker_ocr)
                        )
                    else:
                        avatar_state, classified_text, classified_confidence = (
                            self.avatar_state_classifier.classify(avatar, worker_ocr)
                        )
                    if classified_text:
                        avatar_text, avatar_confidence = classified_text, classified_confidence
                if forced_seat_validation and avatar_state in ("waiting", "away", "empty"):
                    action, text, confidence = "waiting", avatar_text, avatar_confidence
                    forced_action = None
                job["avatarStateOcrMs"] = round(max(0, time.time() - avatar_stage_started) * 1000, 1)
                evidence_source = "action_ocr" if action != "waiting" else "avatar_ocr"
                if "弃牌" in avatar_text and action == "waiting":
                    action = "fold"
                    confidence = avatar_confidence
                if action == "waiting" and self._avatar_text_is_allin(
                        avatar_text, job.get("expectedActor")):
                    action, confidence = "allin", avatar_confidence
                if action == "waiting":
                    if avatar_state == "fold" or any(token in avatar_text for token in ("弃牌", "弃", "fold")):
                        action, confidence = "fold", avatar_confidence
                    elif avatar_state == "allin" or any(token in avatar_text for token in ("全下", "allin", "all-in")):
                        action, confidence = "allin", avatar_confidence
                bet = self._extract_bet(text)
                investment_text = ""
                investment_stage_started = time.time()
                if action == "waiting" and forced_action:
                    action = forced_action
                forced_amount = job.get("forcedAmount")
                if action in ("blind", "straddle") and forced_amount not in (None, 0):
                    bet = float(forced_amount)
                    investment_text = f"known_{action}:{bet:g}"
                elif action == "call" and job.get("knownCallAmount") not in (None, 0):
                    bet = float(job["knownCallAmount"])
                elif action in ("bet", "raise", "reraise") and job.get("knownInvestmentAmount") not in (None, 0):
                    bet = float(job["knownInvestmentAmount"])
                    investment_text = str(job.get("knownInvestmentText") or "")
                elif action == "call" and investment is None:
                    confirmed_call_amount = float(job.get("highestBetAtCapture") or 0)
                    if confirmed_call_amount > 0:
                        bet = confirmed_call_amount
                        investment_text = f"rule:call={bet:g}"
                elif investment is not None and action in (
                        "blind", "post_blind", "straddle", "call", "bet", "raise", "reraise", "allin"):
                    fast_amount_only = (
                        job.get("triggerSource") == "forced_bet_scan" and action == "straddle"
                    ) or (action == "allin" and job.get("expectedActor"))
                    investment_height, investment_width = investment.shape[:2]
                    fast_crops = (
                        investment[int(investment_height * .25):int(investment_height * .75), :],
                        investment[int(investment_height * .4):int(investment_height * .92),
                                   :int(investment_width * .75)],
                        investment[int(investment_height * .4):int(investment_height * .92),
                                   int(investment_width * .18):],
                    )
                    fast_crops = (investment,) + fast_crops
                    fast_candidates = []
                    for fast_crop in fast_crops:
                        fast_text, fast_confidence = ocr_line(cv2.resize(
                            fast_crop, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC))
                        fast_bet = self._extract_investment_amount(fast_text)
                        if (fast_bet not in (None, 0) and ("." in fast_text or "$" in fast_text) and
                                fast_confidence >= .55):
                            fast_candidates.append((fast_confidence, fast_text, fast_bet))
                            break
                    if fast_candidates:
                        _, investment_text, bet = max(fast_candidates)
                    elif not fast_amount_only:
                        investment_text, _ = ocr_line(
                            cv2.resize(investment, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC))
                    if not fast_amount_only and ("$" not in investment_text or "." not in investment_text or
                            len(re.sub(r"\D", "", investment_text)) < 3):
                        right_crop = investment[:, int(investment.shape[1] * .2):]
                        right_text, right_confidence = ocr_line(
                            cv2.resize(right_crop, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC))
                        right_bet = self._extract_investment_amount(right_text)
                        if (right_bet not in (None, 0) and "$" in right_text and "." in right_text and
                                right_confidence >= .55):
                            investment_text = right_text
                    investment_bet = self._extract_bet(investment_text)
                    if investment_bet in (None, 0):
                        investment_bet = self._extract_investment_amount(investment_text)
                    if investment_bet not in (None, 0):
                        bet = investment_bet
                    if not fast_amount_only and action != "call" and (bet in (None, 0) or "." not in investment_text):
                        verified_text, verified_confidence = ocr_detected_line(
                            cv2.resize(investment, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC))
                        verified_bet = self._extract_investment_amount(verified_text)
                        if verified_bet is not None and verified_confidence >= .72:
                            investment_text, bet = verified_text, verified_bet
                    elif not fast_amount_only and action != "call" and "." not in investment_text:
                        verified_text, verified_confidence = ocr_detected_line(
                            cv2.resize(investment, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC))
                        verified_bet = self._extract_investment_amount(verified_text)
                        if (verified_bet is not None and "." in verified_text and
                                verified_confidence >= .72):
                            investment_text, bet = verified_text, verified_bet
                    if not fast_amount_only and bet in (None, 0) and action in (
                            "post_blind", "straddle", "call", "bet", "raise", "reraise", "allin"):
                        verified_text, verified_confidence = ocr_detected_line(
                            cv2.resize(investment, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC))
                        verified_bet = self._extract_investment_amount(verified_text)
                        if verified_bet is not None and verified_confidence >= .72:
                            investment_text, bet = verified_text, verified_bet
                    if (not fast_amount_only and bet is not None and bet >= 10 and "." not in investment_text and
                            len(re.sub(r"\D", "", investment_text)) <= 3):
                        verified_text, verified_confidence = ocr_detected_line(
                            cv2.resize(investment, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC))
                        verified_bet = self._extract_investment_amount(verified_text)
                        if verified_bet is not None and "." in verified_text:
                            investment_text, bet = verified_text, verified_bet
                job["investmentOcrMs"] = round(max(0, time.time() - investment_stage_started) * 1000, 1)
                pot_after = job.get("potAfter")
                if (bet is not None and bet >= 10 and pot_after is not None and 0 < pot_after < 5 and
                        "." not in investment_text and bet > pot_after * 20):
                    cents = bet / 100
                    if cents <= max(2, pot_after * 8):
                        bet = cents
                if bet == 0 and action in ("post_blind", "straddle", "raise", "call"):
                    numbers = [float(value) for value in re.findall(r"\d+(?:\.\d+)?", text)]
                    bet = numbers[-1] if len(numbers) == 1 else None
                stack_zero_evidence = False
                stack_text = ""
                stack_confidence = 0.0
                if (action == "allin" and job.get("expectedActor") and
                        stack_image is not None and stack_image.size):
                    stack_height, stack_width = stack_image.shape[:2]
                    stack_tight = stack_image[int(stack_height * .20):int(stack_height * .70),
                                              int(stack_width * .45):]
                    stack_text, stack_confidence = ocr_line(cv2.resize(
                        stack_tight, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC))
                    stack_zero_evidence = (self._is_zero_stack_text(stack_text) and
                                           "$" in stack_text and stack_confidence >= .55)
                    if not stack_zero_evidence:
                        detected_text, detected_confidence = ocr_detected_line(cv2.resize(
                            stack_image, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC))
                        if detected_confidence > stack_confidence:
                            stack_text, stack_confidence = detected_text, detected_confidence
                        stack_zero_evidence = (self._is_zero_stack_text(stack_text) and
                                               stack_confidence >= .45)
                    if not stack_zero_evidence:
                        line_text, line_confidence = ocr_line(cv2.resize(
                            stack_image, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC))
                        if line_confidence > stack_confidence:
                            stack_text, stack_confidence = line_text, line_confidence
                        stack_zero_evidence = (self._is_zero_stack_text(stack_text) and
                                               stack_confidence >= .45)
                if stack_zero_evidence and investment is not None and investment.size:
                    if (action == "allin" and bet not in (None, 0) and
                            "$" in investment_text):
                        job["stackZeroAmountReuse"] = True
                        action, confidence = "allin", max(float(confidence or 0), .9)
                        investment = None
                if stack_zero_evidence and investment is not None and investment.size:
                    investment_height, investment_width = investment.shape[:2]
                    investment_tight = investment[int(investment_height * .40):int(investment_height * .92),
                                                  :int(investment_width * .75)]
                    amount_text, amount_confidence = ocr_line(cv2.resize(
                        investment_tight, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC))
                    amount = self._extract_investment_amount(amount_text)
                    if (amount in (None, 0) or amount_confidence < .55 or
                            "$" not in amount_text):
                        amount_text, amount_confidence = ocr_detected_line(cv2.resize(
                            investment, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC))
                        amount = self._extract_investment_amount(amount_text)
                    if amount not in (None, 0):
                        investment_text, bet = amount_text, amount
                        action, confidence = "allin", max(float(confidence or 0), .9,
                                                            float(amount_confidence or 0))
                job.update(action=action, text=text, investmentText=investment_text,
                           confidence=float(confidence or 0),
                           avatarText=avatar_text, avatarState=avatar_state, bet=bet, evidenceSource=evidence_source,
                           recognizedAt=time.time())
                job["stackText"] = stack_text
                job["stackZeroEvidence"] = stack_zero_evidence
                job["stackConfidence"] = stack_confidence
                received_at = job.get("frameReceivedAt")
                job["queueLatencyMs"] = (round(max(0, job["ocrStartedAt"] - received_at) * 1000, 1)
                                         if received_at else None)
                enqueued_at = job.get("ocrEnqueuedAt")
                job["preEnqueueLatencyMs"] = (round(max(0, enqueued_at - received_at) * 1000, 1)
                                               if received_at and enqueued_at else None)
                job["actualQueueLatencyMs"] = (round(max(0, job["ocrStartedAt"] - enqueued_at) * 1000, 1)
                                                if enqueued_at else None)
                job["ocrDurationMs"] = round(max(0, job["recognizedAt"] - job["ocrStartedAt"]) * 1000, 1)
                self.action_ocr_trace.append({key: job.get(key) for key in (
                    "videoSecond", "frameSequence", "handId", "street", "index", "colorAction",
                    "triggerSource", "expectedActionProbe", "capsuleDetected", "capsuleEpoch", "action",
                    "text", "avatarText", "avatarState", "investmentText", "bet",
                    "fastInvestmentText", "fastInvestmentConfidence", "fastInvestmentAmount",
                    "queueLatencyMs", "preEnqueueLatencyMs", "actualQueueLatencyMs", "ocrDurationMs",
                    "actionTextOcrMs", "avatarStateOcrMs", "investmentOcrMs")})
                self.action_ocr_results.put(job)
                self.action_ocr_completed += 1
            finally:
                with self.action_ocr_pending_lock:
                    index = job.get("index")
                    deferred = self.action_ocr_deferred_jobs.pop(index, None)
                    same_confirmed_capsule = bool(
                        deferred and job.get("action") != "waiting" and
                        deferred.get("capsuleDetected") and job.get("capsuleDetected") and
                        deferred.get("handId") == job.get("handId") and
                        deferred.get("street") == job.get("street") and
                        deferred.get("capsuleEpoch") == job.get("capsuleEpoch")
                    )
                    if same_confirmed_capsule:
                        deferred = None
                    if deferred is None:
                        self.action_ocr_pending_seats.discard(index)
                    else:
                        try:
                            self._enqueue_action_ocr(deferred)
                        except queue.Full:
                            self.action_ocr_pending_seats.discard(index)
                            self.action_ocr_dropped += 1
                self.action_ocr_queue.task_done()

    def _avatar_ocr_loop(self):
        worker_ocr = RapidOCR(intra_op_num_threads=1, inter_op_num_threads=1)
        avatar_cache = {}
        avatar_full_state = {}
        try:
            warmup = self._ocr_warmup_image()
            worker_ocr(warmup, use_det=False, use_cls=False, use_rec=True)
            worker_ocr(warmup)
        except Exception as error:
            self.ocr_warmup_errors.append({"channel": "avatar", "error": str(error)})
        finally:
            self._mark_ocr_worker_ready("avatar")
        training_dir = os.environ.get("AVATAR_OCR_TRAINING_DIR")
        if training_dir:
            Path(training_dir).mkdir(parents=True, exist_ok=True)
        while True:
            _, _, job = self.avatar_ocr_queue.get()
            try:
                job["ocrStartedAt"] = time.time()
                avatar = job.pop("avatar", None)
                investment = job.pop("investment", None)
                state, text, confidence = ("unknown", "", 0.0)
                avatar_line_started = time.time()
                if avatar is not None and self.avatar_state_classifier is not None:
                    key = (avatar.shape, hashlib.blake2b(avatar, digest_size=8).digest())
                    cached = avatar_cache.get(key)
                    if cached is None:
                        cached = self.avatar_state_classifier.classify_line(avatar, worker_ocr)
                        if len(avatar_cache) >= 512:
                            avatar_cache.pop(next(iter(avatar_cache)))
                        avatar_cache[key] = cached
                    state, text, confidence = cached
                    job["avatarLineOcrMs"] = round(max(0, time.time() - avatar_line_started) * 1000, 1)
                    previous_full = avatar_full_state.get(job.get("index"))
                    thinking_cooldown = bool(
                        previous_full and previous_full[0] == "thinking" and
                        time.time() - previous_full[1] < 1.0 and
                        job.get("expectedActor") and not job.get("visualFoldCandidate")
                    )
                    if (state == "unknown" and not thinking_cooldown and
                            not job.get("fastLineOnly") and
                            (job.get("expectedActor") or job.get("visualFoldCandidate") or
                             (job.get("avatarChanged") and not text.strip())) and
                            job.get("visualFoldCandidate") and not text.strip()):
                        avatar_full_started = time.time()
                        state, text, confidence = self.avatar_state_classifier.classify(avatar, worker_ocr)
                        job["avatarFullOcrMs"] = round(max(0, time.time() - avatar_full_started) * 1000, 1)
                        avatar_full_state[job.get("index")] = (state, time.time())
                    if training_dir and state in ("fold", "thinking", "waiting", "away"):
                        sample_name = (f"{job.get('videoSecond', 0):010.3f}-seat{job.get('index', 0) + 1}-"
                                       f"{state}-{job.get('frameSequence', 0)}.jpg")
                        cv2.imencode(".jpg", avatar, [cv2.IMWRITE_JPEG_QUALITY, 96])[1].tofile(
                            str(Path(training_dir) / sample_name))
                job.setdefault("avatarLineOcrMs", round(max(0, time.time() - avatar_line_started) * 1000, 1))
                job.setdefault("avatarFullOcrMs", 0.0)
                if self._avatar_text_is_allin(text, job.get("expectedActor")):
                    state = "allin"
                if "弃牌" in text or text.strip() == "弃":
                    state = "fold"
                if "空" in text:
                    state = "empty"
                bet = None
                investment_text = ""
                fast_investment_text = ""
                fast_investment_confidence = 0.0
                normalized_avatar_text = text.lower().replace(" ", "")
                if (state == "allin" or self._avatar_text_is_allin(
                        normalized_avatar_text, job.get("expectedActor"))) and investment is not None:
                    enlarged = cv2.resize(investment, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
                    investment_height, investment_width = investment.shape[:2]
                    tight = investment[int(investment_height * .40):int(investment_height * .92),
                                       :int(investment_width * .75)]
                    tight = cv2.resize(tight, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
                    result, _ = worker_ocr(tight, use_det=False, use_cls=False, use_rec=True)
                    if result:
                        fast_investment_text = str(result[0][0])
                        fast_investment_confidence = float(result[0][1])
                    fast_amount = self._extract_investment_amount(fast_investment_text)
                    if (fast_amount not in (None, 0) and fast_investment_confidence >= .55 and
                            ("$" in fast_investment_text or "." in fast_investment_text or
                             fast_amount >= 1)):
                        investment_text, bet = fast_investment_text, fast_amount
                    else:
                        result, _ = worker_ocr(enlarged, use_det=False, use_cls=False, use_rec=True)
                        investment_text = str(result[0][0]) if result else ""
                        detected, _ = worker_ocr(enlarged)
                        detected_text = " ".join(str(item[1]) for item in detected) if detected else ""
                        gray = cv2.cvtColor(enlarged, cv2.COLOR_BGR2GRAY)
                        binary = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)[1]
                        binary_result, _ = worker_ocr(binary)
                        binary_text = (" ".join(str(item[1]) for item in binary_result)
                                       if binary_result else "")
                        if "$" in binary_text:
                            detected_text = binary_text
                        if "$" in detected_text or not investment_text:
                            investment_text = detected_text
                        bet = self._extract_investment_amount(investment_text)
                    job["investmentEvidence"] = investment.copy()
                    job["fastInvestmentText"] = fast_investment_text
                    job["fastInvestmentConfidence"] = fast_investment_confidence
                job.update(action="allin" if state == "allin" else "waiting", text="", confidence=confidence,
                           avatarText=text, avatarState=state, bet=bet,
                           investmentText=investment_text,
                           evidenceSource="avatar_ocr", recognizedAt=time.time())
                received_at = job.get("frameReceivedAt")
                job["queueLatencyMs"] = (round(max(0, job.get("ocrStartedAt", job["recognizedAt"]) - received_at) * 1000, 1)
                                         if received_at else None)
                enqueued_at = job.get("ocrEnqueuedAt")
                job["preEnqueueLatencyMs"] = (round(max(0, enqueued_at - received_at) * 1000, 1)
                                               if received_at and enqueued_at else None)
                job["actualQueueLatencyMs"] = (round(max(0, job.get("ocrStartedAt", job["recognizedAt"]) - enqueued_at) * 1000, 1)
                                                if enqueued_at else None)
                job["ocrDurationMs"] = round(max(0, job["recognizedAt"] - job.get("ocrStartedAt", job["recognizedAt"])) * 1000, 1)
                self.action_ocr_trace.append({key: job.get(key) for key in (
                    "videoSecond", "frameSequence", "handId", "street", "index",
                    "triggerSource", "expectedActionProbe", "action", "avatarText", "avatarState",
                    "investmentText", "bet", "queueLatencyMs", "preEnqueueLatencyMs",
                    "actualQueueLatencyMs", "ocrDurationMs", "avatarLineOcrMs", "avatarFullOcrMs")})
                self.action_ocr_results.put(job)
            finally:
                with self.avatar_ocr_pending_lock:
                    index = job.get("index")
                    deferred = self.avatar_ocr_deferred_jobs.pop(index, None)
                    if deferred is None:
                        self.avatar_ocr_pending_seats.discard(index)
                    else:
                        try:
                            self._enqueue_avatar_ocr(deferred)
                        except queue.Full:
                            self.avatar_ocr_pending_seats.discard(index)
                self.avatar_ocr_queue.task_done()

    def _enqueue_avatar_ocr(self, job):
        job.setdefault("capturedRuntimeId", job.get("runtimeId", self.runtime_id))
        job.setdefault("capturedTableSession", job.get("tableSession", self.table_session))
        job.setdefault("capturedHandId", job.get("handId"))
        job.setdefault("capturedStreet", job.get("street"))
        job.setdefault("capturedObservedAt", job.get("observedAt"))
        job.setdefault("capturedFrameSequence", job.get("frameSequence"))
        self._bind_action_capture_window(job)
        expected = getattr(self, "formal_expected_seat", None)
        index = job.get("index")
        count = len(TABLE_LAYOUTS[self.layout])
        distance = (index - expected) % count if expected is not None and index is not None else count
        priority = (0 if job.get("chainGapProbe") else
                    count * 4 + distance if job.get("occupancyProbe") else
                    distance + (0 if job.get("visualFoldCandidate") else count))
        with self.avatar_ocr_sequence_lock:
            self.avatar_ocr_sequence += 1
            sequence = self.avatar_ocr_sequence
        job["ocrEnqueuedAt"] = time.time()
        self.avatar_ocr_queue.put_nowait((priority, sequence, job))

    def _bind_action_capture_window(self, job):
        timeline = getattr(self, "action_timeline", None)
        if timeline is None:
            return
        captured_hand = job.get("capturedHandId", job.get("handId"))
        captured_at = job.get("capturedObservedAt", job.get("observedAt"))
        captured_frame = job.get("capturedFrameSequence", job.get("frameSequence"))
        captured_video = job.get("videoSecond")
        actual_street = timeline.street_for_point(
            captured_hand, captured_at, captured_frame, captured_video)
        if actual_street:
            job["capturedStreet"] = actual_street
        context = timeline.capture_context(
            captured_hand,
            job.get("capturedStreet", job.get("street")),
            captured_at,
            captured_frame,
            captured_video,
        )
        job.setdefault("capturedActionRound", context.get("actionRound"))
        job.setdefault("capturedTimeWindowId", context.get("windowId"))

    @staticmethod
    def _avatar_text_is_allin(text, expected_actor=False):
        normalized = "".join(character for character in str(text).lower()
                             if character.isalnum() or "\u4e00" <= character <= "\u9fff")
        return ("allin" in normalized or "\u5168\u4e0b" in normalized or
                (bool(expected_actor) and ("alin" in normalized or
                                           normalized.startswith("ain"))))

    @staticmethod
    def _is_zero_stack_text(text):
        normalized = re.sub(r"\s+", "", str(text or "")).lower()
        if not normalized:
            return False
        normalized = normalized.replace("o", "0")
        return bool(re.search(r"(?:\$|￥|¥)0(?:\.0{1,2})?$", normalized) or
                    normalized in {"0", "0.0", "0.00", "$0", "$0.0", "$0.00"})

    def _enqueue_action_ocr(self, job):
        job.setdefault("capturedRuntimeId", job.get("runtimeId", self.runtime_id))
        job.setdefault("capturedTableSession", job.get("tableSession", self.table_session))
        job.setdefault("capturedHandId", job.get("handId"))
        job.setdefault("capturedStreet", job.get("street"))
        job.setdefault("capturedObservedAt", job.get("observedAt"))
        job.setdefault("capturedFrameSequence", job.get("frameSequence"))
        self._bind_action_capture_window(job)
        expected = getattr(self, "formal_expected_seat", None)
        trigger = job.get("triggerSource")
        if job.get("index") == expected or job.get("chainGapProbe"):
            priority = 0
        elif job.get("capsuleDetected"):
            priority = 1
        elif trigger == "forced_bet_scan":
            priority = 2
        elif trigger == "pending_bet":
            priority = 3
        elif trigger == "unresolved_retry":
            priority = 5
        else:
            priority = 4
        with self.action_ocr_sequence_lock:
            self.action_ocr_sequence += 1
            sequence = self.action_ocr_sequence
        job["ocrEnqueuedAt"] = time.time()
        self.action_ocr_queue.put_nowait((priority, sequence, job))

    def _defer_action_ocr_job(self, index, job):
        deferred = self.action_ocr_deferred_jobs.get(index)
        if deferred is None:
            self.action_ocr_deferred_jobs[index] = job
            return job
        same_capsule = (deferred.get("capsuleDetected") and job.get("capsuleDetected") and
                        deferred.get("capsuleEpoch") == job.get("capsuleEpoch"))
        if same_capsule:
            deferred.update(job)
            return deferred
        def evidence_priority(item):
            return (
                bool(item.get("capsuleDetected")),
                bool(item.get("chainGapProbe")),
                bool(item.get("forcedAction")),
                bool(item.get("expectedActionProbe") or item.get("priorStreetProbe")),
                bool(item.get("visualFoldCandidate")),
                bool(item.get("pendingBet")),
            )
        if evidence_priority(job) > evidence_priority(deferred):
            self.action_ocr_deferred_jobs[index] = job
            return job
        return deferred

    @staticmethod
    def _classify_action_color(crop):
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        hue, saturation, value = cv2.split(hsv)
        orange = float(np.mean((hue < 25) & (saturation > 140) & (value > 120)))
        blue = float(np.mean((hue > 95) & (hue < 125) & (saturation > 140) & (value > 120)))
        green_pixels = (hue > 35) & (hue < 90) & (saturation > 90)
        green_values = value[green_pixels]
        green = 0.0
        if green_values.size:
            felt_value = float(np.median(green_values))
            for mask in (
                green_pixels & (value > 70) & (value < felt_value - 8),
                green_pixels & (value > felt_value + 15),
            ):
                contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL,
                                               cv2.CHAIN_APPROX_SIMPLE)
                for contour in contours:
                    x, y, width, height = cv2.boundingRect(contour)
                    area_ratio = cv2.contourArea(contour) / max(crop.shape[0] * crop.shape[1], 1)
                    if area_ratio >= .03 and width / max(height, 1) >= 2.0 and width >= crop.shape[1] * .35:
                        green = area_ratio
                        break
                if green:
                    break
        if orange >= .12:
            return "investment", min(.98, .72 + orange)
        if blue >= .12:
            return "call", min(.98, .72 + blue)
        if green:
            return "check", min(.98, .82 + green)
        return None, 0

    @staticmethod
    def _is_straddle_label(crop):
        if crop.size == 0:
            return False
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        hue, saturation, value = cv2.split(hsv)
        purple = (hue >= 125) & (hue <= 165) & (saturation >= 90) & (value >= 80)
        return float(np.mean(purple)) >= .015

    def _drain_action_ocr_results(self, hero_buttons_visible=False,
                                  hero_button_frame_sequence=None):
        events = []
        while True:
            try:
                result = self.action_ocr_results.get_nowait()
            except queue.Empty:
                break
            selected_capture = result.pop("selectedCropCapture", None)
            if selected_capture:
                result["capturedRuntimeId"] = selected_capture.get(
                    "runtimeId", result.get("capturedRuntimeId"))
                result["capturedTableSession"] = selected_capture.get(
                    "tableSession", result.get("capturedTableSession"))
                result["capturedHandId"] = selected_capture.get(
                    "handId", result.get("capturedHandId"))
                result["capturedStreet"] = selected_capture.get(
                    "street", result.get("capturedStreet"))
                result["capturedObservedAt"] = selected_capture.get(
                    "observedAt", result.get("capturedObservedAt"))
                result["capturedFrameSequence"] = selected_capture.get(
                    "frameSequence", result.get("capturedFrameSequence"))
                if selected_capture.get("videoSecond") is not None:
                    result["videoSecond"] = selected_capture["videoSecond"]
                result.pop("capturedActionRound", None)
                result.pop("capturedTimeWindowId", None)
                self._bind_action_capture_window(result)
            captured_runtime = result.get("capturedRuntimeId", result.get("runtimeId"))
            captured_session = result.get("capturedTableSession", result.get("tableSession"))
            captured_hand = result.get("capturedHandId", result.get("handId"))
            captured_street = result.get("capturedStreet", result.get("street"))
            if captured_runtime is not None and captured_runtime != self.runtime_id:
                continue
            if captured_session is not None and captured_session != self.table_session:
                continue
            if captured_hand != self.hand_state.get("id"):
                continue
            result.update(
                runtimeId=captured_runtime,
                tableSession=captured_session,
                handId=captured_hand,
                street=captured_street,
                observedAt=result.get("capturedObservedAt", result.get("observedAt")),
                frameSequence=result.get("capturedFrameSequence", result.get("frameSequence")),
            )
            action = result.get("action")
            bet = result.get("bet")
            captured_highest = result.get("highestBetAtCapture")
            captured_actor_bet = float(result.get("actorBetAtCapture") or 0)
            if (action == "call" and captured_highest is not None and
                    float(captured_highest) <= captured_actor_bet + .001 and
                    result.get("capsuleDetected") and not result.get("explicitActionText")):
                action, bet = "check", 0.0
                result.update(action=action, bet=bet,
                              evidenceSource="capture_context_zero_price_check")
            result_frame_sequence = result.get("frameSequence")
            delayed_prior_result = self._is_delayed_prior_street_result(result)
            if (result_frame_sequence is not None and
                    result_frame_sequence <= self.special_scene_last_frame_sequence and
                    not delayed_prior_result):
                continue
            capsule_epoch = result.get("capsuleEpoch")
            if (capsule_epoch is not None and
                    result.get("index") in self.hand_start_visible_capsules and
                    capsule_epoch <= self.hand_start_capsule_epochs.get(result.get("index"), -1)):
                continue
            avatar_state = result.get("avatarState", "unknown")
            tracker = self.seat_trackers.get(result.get("index"), {})
            if delayed_prior_result:
                self._record_delayed_prior_street_result(result, tracker)
                continue
            if self._promote_persistent_allin_to_prior_street(result, tracker):
                continue
            if result.get("street") != self.hand_state.get("street"):
                continue
            if result.get("occupancyProbe"):
                if avatar_state == "empty":
                    self._set_seat_occupancy(result["index"], "empty", "fast_avatar_empty_ocr",
                                             result.get("observedAt"), result.get("videoSecond"))
                elif avatar_state in ("fold", "thinking", "waiting", "away", "allin"):
                    self._set_seat_occupancy(result["index"], "occupied", "fast_avatar_state_ocr",
                                             result.get("observedAt"), result.get("videoSecond"))
                continue
            if avatar_state == "empty":
                if not self._set_seat_occupancy(result["index"], "empty", "action_avatar_empty_ocr",
                                                result.get("observedAt"), result.get("videoSecond")):
                    continue
                tracker.update(lastAction="empty", visualState="empty",
                               visualStateText=result.get("avatarText", ""),
                               visualStateConfidence=result.get("confidence", 0),
                               visualStateObservedAt=result.get("observedAt"),
                               visualStateVideoSecond=result.get("videoSecond"))
                acted_this_hand = any(
                    item.get("handId") == result.get("handId") and
                    item.get("seat") == result.get("index") + 1
                    for item in self.action_log
                )
                if not acted_this_hand:
                    self.hand_participants.setdefault(result.get("handId"), set()).discard(result.get("index"))
                tracker["excludedDuringHandId"] = result.get("handId")
                tracker["excludedObservedAt"] = result.get("observedAt", result.get("videoSecond"))
                if result.get("index") == getattr(self, "formal_expected_seat", None):
                    self.formal_expected_seat = self._next_opponent_seat(result["index"])
                    self._promote_expected_fold_chain()
                continue
            if tracker.get("occupancy") == "empty":
                continue
            if self._betting_round_closed(result.get("handId"), result.get("street")):
                explicit_result = (
                    action in ("fold", "check", "call", "bet", "raise", "reraise", "allin") or
                    avatar_state in ("fold", "allin") or result.get("stackZeroEvidence")
                )
                result_frame = result.get("frameSequence")
                latest_frame = max((item.get("frameSequence") for item in self.action_log
                                    if item.get("handId") == result.get("handId") and
                                    item.get("street") == result.get("street") and
                                    isinstance(item.get("frameSequence"), (int, float))),
                                   default=None)
                is_new_frame = (result_frame is not None and
                                (latest_frame is None or result_frame > latest_frame))
                if not (explicit_result and is_new_frame):
                    continue
            hero_index = 4 if self.layout == "8max" else 3
            button_frame_boundary = (
                hero_button_frame_sequence if hero_buttons_visible else
                self.hero_button_last_visible_frame_sequence
                if (self.hero_button_last_visible_hand_id == result.get("handId") and
                    self.hero_button_last_visible_street == result.get("street")) else None
            )
            hero_result_precedes_buttons = bool(
                button_frame_boundary is not None and
                (result_frame_sequence is None or
                 result_frame_sequence <= button_frame_boundary)
            )
            if result.get("index") == hero_index and hero_result_precedes_buttons:
                continue
            if not self._accept_action_result_after_hero_turn(
                    result, hero_index, button_frame_boundary):
                continue
            existing_capsule = next((item for item in reversed(self.action_log)
                                     if item.get("handId") == result.get("handId") and
                                     item.get("street") == result.get("street") and
                                     item.get("seat") == result.get("index") + 1 and
                                     item.get("action") == action and
                                     capsule_epoch is not None and
                                     item.get("capsuleEpoch") == capsule_epoch), None)
            old_investment_text = str(existing_capsule.get("investmentText") or "") if existing_capsule else ""
            new_investment_text = str(result.get("investmentText") or "")
            old_decimals = len(old_investment_text.rsplit(".", 1)[1]) if "." in old_investment_text else 0
            new_decimals = len(new_investment_text.rsplit(".", 1)[1]) if "." in new_investment_text else 0
            old_fraction = old_investment_text.rsplit(".", 1)[1] if old_decimals else ""
            new_fraction = new_investment_text.rsplit(".", 1)[1] if new_decimals else ""
            more_complete_decimal = bool(
                old_decimals == 1 and new_decimals == 2 and
                len(re.sub(r"\D", "", new_investment_text)) >
                len(re.sub(r"\D", "", old_investment_text)) and
                new_fraction.endswith(old_fraction)
            )
            existing_second = self._event_second(existing_capsule or {})
            result_second = self._event_second(result)
            timely_recheck = (existing_second is not None and result_second is not None and
                              0 <= float(result_second) - float(existing_second) <= 1.5)
            intervening_action = bool(existing_capsule and any(
                item.get("handId") == result.get("handId") and
                item.get("street") == result.get("street") and
                item.get("seat") != result.get("index") + 1 and
                float(self._event_second(item) or 0) > float(existing_second or 0)
                for item in self.action_log[self.action_log.index(existing_capsule) + 1:]
            ))
            reopened_capsule = bool(
                existing_capsule and action == "call" and
                self._action_reopened_after(
                    self.action_log, existing_capsule, result.get("index") + 1)
            )
            can_correct_capsule = bool(existing_capsule is not None and timely_recheck and
                                       not intervening_action)
            if existing_capsule is not None and not can_correct_capsule:
                old_investment_text = ""
                old_decimals = 0
            clearer_amount = (existing_capsule is not None and result.get("bet") not in (None, 0) and
                              can_correct_capsule and
                              ((not old_decimals and new_decimals) or
                               (old_decimals >= 3 and 1 <= new_decimals <= 2) or
                               more_complete_decimal) and
                              result.get("bet") != existing_capsule.get("amount"))
            missing_leading_digit = bool(
                existing_capsule is not None and result.get("bet") not in (None, 0) and
                str(result.get("investmentText") or "").lstrip().startswith("$.") and
                float(existing_capsule.get("amount") or 0) >= float(result["bet"]) * 5
            )
            if missing_leading_digit:
                clearer_amount = False
            lower_plausible_amount = bool(
                existing_capsule is not None and result.get("bet") not in (None, 0) and
                timely_recheck and not intervening_action and
                float(result["bet"]) < float(existing_capsule.get("amount") or 0) and
                ("$" not in old_investment_text or old_decimals >= 3) and
                existing_capsule.get("potAfter") not in (None, 0) and
                float(existing_capsule.get("amount") or 0) > float(existing_capsule["potAfter"]) * 4 and
                float(result["bet"]) <= float(existing_capsule["potAfter"]) * 2
            )
            clearer_amount = clearer_amount or lower_plausible_amount
            if clearer_amount and existing_capsule.get("action") == "call":
                confirmed_highest = max((float(item.get("amount") or 0) for item in self.action_log
                                         if item.get("handId") == result.get("handId") and
                                         item.get("street") == result.get("street") and
                                         item.get("seat") != result.get("index") + 1 and
                                         item.get("action") in ("bet", "raise", "reraise", "allin", "straddle")),
                                        default=0.0)
                if confirmed_highest and abs(float(result["bet"]) - confirmed_highest) > max(.01, confirmed_highest * .08):
                    clearer_amount = False
            if clearer_amount:
                old_amount = float(existing_capsule.get("amount") or 0)
                existing_capsule.update(
                    amount=result["bet"],
                    increase=max(0.0, float(existing_capsule.get("increase") or 0) +
                                 result["bet"] - old_amount),
                    investmentText=result.get("investmentText", ""),
                    evidence=("same_capsule_lower_plausible_amount" if lower_plausible_amount
                              else "same_capsule_clear_decimal_amount"),
                    confidence=max(float(existing_capsule.get("confidence") or 0),
                                   float(result.get("confidence") or 0)),
                )
                tracker["stableBet"] = result["bet"]
                continue
            if existing_capsule is not None and not reopened_capsule:
                continue
            if avatar_state != "unknown":
                tracker["visualState"] = avatar_state
                tracker["visualStateText"] = result.get("avatarText", "")
                tracker["visualStateConfidence"] = result.get("confidence", 0)
                tracker["visualStateObservedAt"] = result.get("observedAt")
                tracker["visualStateVideoSecond"] = result.get("videoSecond")
                if avatar_state in ("away", "waiting"):
                    acted_this_hand = any(
                        item.get("handId") == result.get("handId") and
                        item.get("seat") == result.get("index") + 1
                        for item in self.action_log
                    )
                    if not acted_this_hand:
                        tracker["handEligible"] = False
                        self.hand_participants.setdefault(result.get("handId"), set()).discard(result.get("index"))
                        if result.get("index") == getattr(self, "formal_expected_seat", None):
                            self.formal_expected_seat = self._next_opponent_seat(result["index"])
                            self._promote_expected_fold_chain()
                    tracker["excludedDuringHandId"] = result.get("handId")
                    tracker["excludedObservedAt"] = result.get(
                        "observedAt", result.get("videoSecond"))
                    self._rebase_forced_bets_after_state_change()
                elif (avatar_state not in ("waiting", "unknown") and
                      tracker.get("joinedDuringHandId") != result.get("handId") and
                      tracker.get("excludedDuringHandId") != result.get("handId")):
                    tracker["handEligible"] = True
            hero_voluntary_signal = (
                result.get("index") == hero_index and
                (action in ("fold", "check", "call", "bet", "raise", "reraise", "allin") or
                 avatar_state in ("fold", "allin"))
            )
            hero_button_candidate = next((
                item for item in reversed(self.action_candidates)
                if item.get("handId") == result.get("handId") and
                item.get("street") == result.get("street") and
                item.get("seat") == hero_index + 1 and
                item.get("action") == "hero_action_unresolved" and
                not item.get("promoted") and not item.get("expired")
            ), None)
            pending_hero_context = bool(
                self.pending_hero_buttons and
                getattr(self, "pending_hero_hand_id", None) in (None, result.get("handId")) and
                getattr(self, "pending_hero_street", None) in (None, result.get("street"))
            )
            if (hero_voluntary_signal and not pending_hero_context and
                    hero_button_candidate is None):
                continue
            if result.get("index") == hero_index and avatar_state == "fold":
                candidate = hero_button_candidate
                if candidate:
                    event = dict(candidate)
                    event.update(action="fold", amount=tracker.get("stableBet", 0.0), increase=0,
                                 videoSecond=result.get("videoSecond", result.get("observedAt")),
                                 observedAt=result.get("observedAt"),
                                 recognizedAt=result.get("recognizedAt", time.time()),
                                 confidence=max(float(result.get("confidence") or 0), .9),
                                 evidence="official_buttons_disappeared+hero_avatar_fold_text",
                                 chainStatus="direct_confirmed", strategyEligible=True)
                    event.pop("visualCandidate", None)
                    if self._append_action_event(event):
                        candidate["promoted"] = True
                        tracker["lastAction"] = "fold"
                        events.append(event)
                    self.pending_hero_buttons = []
                    continue
            if action == "waiting" and result.get("capsuleDetected") and result.get("bet") not in (None, 0):
                unresolved = next((item for item in reversed(self.action_candidates)
                                   if item.get("handId") == result.get("handId") and
                                   item.get("street") == result.get("street") and
                                   item.get("seat") == result.get("index") + 1 and
                                   str(item.get("action", "")).endswith("_amount_unresolved") and
                                   not item.get("promoted") and not item.get("expired")), None)
                if unresolved is not None:
                    event = dict(unresolved)
                    event.pop("visualCandidate", None)
                    event.update(action=event["action"].removesuffix("_amount_unresolved"),
                                 amount=result["bet"],
                                 increase=max(0.0, result["bet"] - float(tracker.get("stableBet") or 0)),
                                 recognizedAt=result.get("recognizedAt", time.time()),
                                 investmentText=result.get("investmentText", ""),
                                 evidence="动作文字+后续投入金额", chainStatus="direct_confirmed",
                                 strategyEligible=True)
                    if self._append_action_event(event):
                        unresolved["promoted"] = True
                        tracker["stableBet"] = result["bet"]
                        tracker["lastAction"] = event["action"]
                        events.append(event)
                    continue
                existing = next((item for item in reversed(self.action_log)
                                 if item.get("handId") == result.get("handId") and
                                 item.get("street") == result.get("street") and
                                 item.get("seat") == result.get("index") + 1 and
                                 item.get("capsuleEpoch") == result.get("capsuleEpoch") and
                                 item.get("amount") is None), None)
                if existing is not None:
                    previous_bet = float(tracker.get("stableBet") or 0)
                    existing["amount"] = result["bet"]
                    existing["increase"] = max(0.0, result["bet"] - previous_bet)
                    existing["evidence"] = "动作文字+后续投入金额"
                    tracker["stableBet"] = result["bet"]
                    continue
                tracker["pendingVisualBet"] = result["bet"]
                tracker["pendingVisualBetHand"] = result.get("handId")
                tracker["pendingVisualBetStreet"] = result.get("street")
                tracker["pendingVisualBetSecond"] = result.get("videoSecond")
            if action == "waiting" and result.get("capsuleDetected"):
                self.action_unresolved_retries[result["index"]] = 3
                candidate = {"time": result.get("recognizedAt", time.time()),
                             "observedAt": result.get("observedAt"), "videoSecond": result.get("videoSecond"),
                             "frameSequence": result.get("frameSequence"), "handId": result.get("handId"),
                             "street": result.get("street"), "seat": result["index"] + 1,
                             "name": result.get("name", ""), "action": "action_text_unresolved",
                             "amount": None, "increase": None, "confidence": result.get("confidence", 0),
                             "evidence": "action_capsule_present_but_text_unreadable"}
                self._append_action_candidate(candidate)
                continue
            if (action == "fold" and avatar_state == "fold" and
                    not self.hand_boundary_confirmed):
                tracker["lastAction"] = "fold"
                continue
            if (action in ("waiting", "fold") and avatar_state == "fold" and
                    not result.get("capsuleDetected") and self.hand_boundary_confirmed):
                if result.get("avatarSignature") is not None:
                    tracker["confirmedFoldSignature"] = result["avatarSignature"]
                late_fold = getattr(self, "prior_street_unresolved", None)
                fold_street = result.get("street")
                fold_second = self._event_second(result)
                processing_second = getattr(self, "recording_second", None)
                if processing_second is None:
                    processing_second = result.get("recognizedAt", result.get("observedAt"))
                if (late_fold and result.get("index") in late_fold.get("seats", set()) and
                        fold_second is not None and late_fold.get("changedAt") is not None and
                        (float(fold_second) <= float(late_fold["changedAt"]) or
                         result.get("index") in late_fold.get("forcedFoldSeats", set())) and
                        processing_second is not None and
                        float(processing_second) >= float(late_fold["changedAt"])):
                    fold_street = late_fold["street"]
                    late_fold["seats"].discard(result.get("index"))
                event = {"time": result.get("recognizedAt", time.time()),
                         "observedAt": result.get("observedAt"),
                         "recognizedAt": result.get("recognizedAt"),
                         "frameSequence": result.get("frameSequence"),
                         "handId": result.get("handId"), "street": fold_street,
                         "sequence": 1, "seat": result["index"] + 1,
                         "name": result.get("name", ""), "action": "fold",
                         "amount": tracker.get("stableBet", 0.0), "increase": 0,
                         "chipsAfter": result.get("chips"), "potAfter": result.get("potAfter"),
                         "confidence": result.get("confidence", 0),
                         "evidence": "头像弃牌文字",
                         "queueLatencyMs": result.get("queueLatencyMs"),
                         "preEnqueueLatencyMs": result.get("preEnqueueLatencyMs"),
                         "actualQueueLatencyMs": result.get("actualQueueLatencyMs"),
                         "ocrDurationMs": result.get("ocrDurationMs")}
                if fold_street != result.get("street"):
                    event["rawObservedSecond"] = event.get("videoSecond")
                    event["observedAt"] = late_fold["changedAt"]
                    event["videoSecond"] = late_fold["changedAt"]
                    event["evidence"] = "avatar_fold_text+next_street_proved_prior_round_closed"
                    if self._append_action_event(event, resolve_prior=False):
                        tracker["lastAction"] = "fold"
                        events.append(event)
                    continue
                if result.get("index") != getattr(self, "formal_expected_seat", None):
                    self._promote_expected_fold_chain()
                expected_index = getattr(self, "formal_expected_seat", None)
                avatar_text = str(result.get("avatarText") or "")
                explicit_fold_text = any(word in avatar_text for word in ACTION_TEXT_WORDS["fold"])
                chain_gap_context = result.get("chainGapContext")
                if not chain_gap_context:
                    chain_gap_context = self._current_street_chain_gap_contexts().get(
                        result.get("index"))
                chain_gap_repair = bool(
                    result.get("chainGapProbe") and explicit_fold_text and
                    chain_gap_context
                )
                if result.get("index") == expected_index or chain_gap_repair:
                    if explicit_fold_text:
                        event["confidence"] = max(.9, float(event.get("confidence") or 0))
                        event["evidence"] = "\u660e\u786e\u5f03\u724c\u6587\u5b57+\u6b63\u786e\u884c\u52a8\u987a\u5e8f"
                        event["inferred"] = False
                    if chain_gap_repair:
                        self._bind_chain_gap_repair_event(
                            event, result, chain_gap_context)
                    expected_after_repair = self.formal_expected_seat
                    if self._append_action_event(event, resolve_prior=True):
                        tracker["lastAction"] = "fold"
                        events.append(event)
                        if chain_gap_repair:
                            self.formal_expected_seat = expected_after_repair
                            event["chainGapRepair"] = True
                            self._publish_confirmed_action_state(event)
                        else:
                            self._promote_expected_fold_chain()
                else:
                    event.update(visualCandidate=True, strategyEligible=False,
                                 evidenceSignals={"avatarText": explicit_fold_text})
                    self._append_action_candidate(event)
                continue
            if action == "waiting":
                continue
            if (getattr(self, "waiting_for_forced_bets", False) and
                    action not in ("blind", "post_blind", "straddle") and
                    result.get("index") != self.formal_expected_seat):
                continue
            if getattr(self, "waiting_for_forced_bets", False) and action == "call":
                forced_highest = max((float(item.get("amount") or 0) for item in self.action_log
                                      if item.get("handId") == result.get("handId") and
                                      item.get("street") == "preflop" and
                                      item.get("action") in ("blind", "post_blind", "straddle")),
                                     default=0.0)
                if (forced_highest <= 0 or bet in (None, 0) or
                        abs(float(bet) - forced_highest) > max(.001, forced_highest * .08)):
                    continue
            if action == "post_blind":
                explicit_forced_text = bool(result.get("explicitActionText"))
                if not explicit_forced_text or bet in (None, 0):
                    continue
            if (action == "straddle" and bet in (None, 0) and
                    result.get("street") == "preflop" and
                    getattr(self, "waiting_for_forced_bets", False)):
                _, big_blind, straddle_seat = self._current_forced_bet_seats()
                confirmed_big = max(
                    (float(item.get("amount") or 0) for item in self.action_log
                     if item.get("handId") == result.get("handId") and
                     item.get("street") == "preflop" and
                     item.get("seat") == big_blind + 1 and item.get("action") == "blind"),
                    default=0.0,
                )
                if result.get("index") == straddle_seat and confirmed_big > 0:
                    bet = round(confirmed_big * 2, 4)
                    result["investmentText"] = "rule:straddle=2bb"
            if action == "check":
                if result.get("street") == "preflop":
                    actor_bet = float(tracker.get("stableBet") or 0)
                    highest_bet = max((float(item.get("amount") or 0) for item in self.action_log
                                       if item.get("handId") == result.get("handId") and
                                       item.get("street") == "preflop" and
                                       item.get("action") in ("blind", "post_blind", "straddle",
                                                              "bet", "raise", "reraise", "allin")),
                                      default=0.0)
                    if (result.get("index") != self.formal_expected_seat or
                            highest_bet > actor_bet + .001):
                        continue
                bet = 0.0
            self.action_unresolved_retries[result["index"]] = 0
            chips = result.get("chips")
            pot_after = result.get("potAfter")
            investment_text = str(result.get("investmentText") or "").strip()
            ambiguous_integer_amount = bool(
                action in ("call", "bet", "raise", "reraise") and
                re.fullmatch(r"\d{1,2}", investment_text) and
                "$" not in investment_text and "." not in investment_text
            )
            if action == "call":
                if captured_highest is None:
                    confirmed_amounts = [float(item.get("amount") or 0) for item in self.action_log
                                         if item.get("handId") == result.get("handId") and
                                         item.get("street") == result.get("street") and
                                         item.get("seat") != result.get("index") + 1 and
                                         item.get("action") in ("bet", "raise", "reraise", "allin")]
                    tracker_amounts = [float(value.get("stableBet") or 0)
                                       for key, value in self.seat_trackers.items()
                                       if key != result.get("index")]
                    highest = max(confirmed_amounts or tracker_amounts, default=0.0)
                    actor_bet = float(tracker.get("stableBet") or 0)
                else:
                    highest = float(captured_highest)
                    actor_bet = captured_actor_bet
                clear_call_amount = bet not in (None, 0) and "." in str(result.get("investmentText") or "")
                stale_actor_amount = bool(
                    bet not in (None, 0) and highest > actor_bet + .001 and
                    abs(float(bet) - actor_bet) <= max(.001, actor_bet * .08)
                )
                if ambiguous_integer_amount:
                    bet = highest if highest > 0 else None
                if stale_actor_amount:
                    bet = highest
                elif highest > 0 and not clear_call_amount and (
                        bet is None or abs(bet - highest) > max(.01, highest * .08)):
                    bet = highest
            elif ambiguous_integer_amount:
                bet = None
            if bet is None and tracker.get("pendingVisualBetHand") == result.get("handId") and \
                    tracker.get("pendingVisualBetStreet") == result.get("street"):
                pending_second = tracker.get("pendingVisualBetSecond")
                result_second = result.get("videoSecond")
                if pending_second is None or result_second is None or abs(result_second - pending_second) <= 3.0:
                    bet = tracker.pop("pendingVisualBet", None)
                    tracker.pop("pendingVisualBetHand", None)
                    tracker.pop("pendingVisualBetStreet", None)
                    tracker.pop("pendingVisualBetSecond", None)
            if result.get("index") == hero_index and self.pending_hero_buttons and action in ("fold", "check", "call", "bet", "raise"):
                prior_hero_bet = float(tracker.get("stableBet") or 0)
                hero_chips_before = (self.pending_hero_chips
                                     if isinstance(self.pending_hero_chips, (int, float)) else None)
                if action in ("call", "bet", "raise"):
                    bet = self._reconcile_hero_total_amount(
                        bet, prior_hero_bet, hero_chips_before, chips)
                event = {"time": result.get("recognizedAt", time.time()),
                         "observedAt": result.get("observedAt"), "recognizedAt": result.get("recognizedAt"),
                         "videoSecond": result.get("videoSecond"),
                         "frameSequence": result.get("frameSequence"), "handId": result.get("handId"),
                         "street": result.get("street"), "sequence": 1, "seat": hero_index + 1,
                         "name": result.get("name", "Zixia888"), "action": action, "amount": bet,
                         "increase": (max(0.0, float(bet) - prior_hero_bet)
                                      if isinstance(bet, (int, float)) else 0.0 if action in ("fold", "check") else None),
                         "chipsBefore": hero_chips_before, "chipsAfter": chips, "potAfter": pot_after,
                         "confidence": result.get("confidence", 0), "evidence": "hero_action_capsule_ocr",
                         "capsuleEpoch": result.get("capsuleEpoch"),
                         "queueLatencyMs": result.get("queueLatencyMs"),
                         "preEnqueueLatencyMs": result.get("preEnqueueLatencyMs"),
                         "actualQueueLatencyMs": result.get("actualQueueLatencyMs"),
                         "ocrDurationMs": result.get("ocrDurationMs")}
                if action in ("call", "bet", "raise") and bet in (None, 0):
                    continue
                if self._append_action_event(event):
                    events.append(event)
                    self.seat_trackers.get(hero_index, {})["lastAction"] = action
                    if isinstance(bet, (int, float)) and action in ("call", "bet", "raise"):
                        self.seat_trackers[hero_index]["stableBet"] = float(bet)
                self.pending_hero_buttons = []
                continue
            if action != "allin" and bet is not None and chips is not None and bet > chips * 1.05:
                continue
            if bet is not None and pot_after is not None and bet > max(50, pot_after * 8):
                continue
            if action == "allin":
                allin_text = f"{result.get('text', '')} {result.get('avatarText', '')}".lower().replace(" ", "")
                explicit_allin = (
                    avatar_state == "allin" and float(result.get("confidence") or 0) >= .9
                ) or self._avatar_text_is_allin(allin_text, result.get("expectedActor")) or (
                    result.get("expectedActor") and result.get("stackZeroEvidence") and
                    bet not in (None, 0) and "$" in str(result.get("investmentText") or "") and
                    float(result.get("confidence") or 0) >= .9
                )
                if not explicit_allin:
                    continue
                investment_digits = re.sub(r"\D", "", str(result.get("investmentText") or ""))
                amount_reconciles = (
                    chips == 0 and bet not in (None, 0) and pot_after not in (None, 0) and
                    float(bet) <= float(pot_after) * 1.05
                )
                if (bet not in (None, 0) and "$" not in str(result.get("investmentText") or "") and
                        len(investment_digits) <= 1 and not amount_reconciles):
                    bet = None
                investment_text = str(result.get("investmentText") or "")
                needs_amount_review = bet in (None, 0) or "." not in investment_text
                crop = result.pop("investmentEvidence", None) if needs_amount_review else None
                if needs_amount_review and crop is None:
                    frame, _ = self._frame_copy()
                    if frame is not None:
                        height, width = frame.shape[:2]
                        box = self._seat_slot_box(result["index"], "investment", width, height)
                        if box:
                            x1, y1, x2, y2 = box
                            crop = frame[max(0, y1):min(height, y2), max(0, x1):min(width, x2)]
                if needs_amount_review and crop is not None and crop.size:
                            enlarged = cv2.resize(crop, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
                            text, _ = self._ocr_line(enlarged)
                            verified = self._extract_investment_amount(text)
                            with self.ocr_lock:
                                detected_result, _ = self.ocr(enlarged)
                            detected = (" ".join(str(item[1]) for item in detected_result)
                                        if detected_result else "")
                            detected_confidence = (min(float(item[2]) for item in detected_result)
                                                   if detected_result else 0.0)
                            detected_bet = self._extract_investment_amount(detected)
                            if detected_bet not in (None, 0) and detected_confidence >= .65:
                                text, verified = detected, detected_bet
                            if verified not in (None, 0):
                                bet = verified
                                result["investmentText"] = text
                event = {"time": result.get("recognizedAt", time.time()),
                         "observedAt": result.get("observedAt"), "recognizedAt": result.get("recognizedAt"),
                         "videoSecond": result.get("videoSecond"),
                         "frameSequence": result.get("frameSequence"), "handId": result.get("handId"),
                         "street": result.get("street"), "sequence": 1, "seat": result["index"] + 1,
                         "name": result.get("name", ""), "action": "allin", "amount": bet,
                         "increase": None, "chipsAfter": chips, "potAfter": pot_after,
                         "confidence": result.get("confidence", 0),
                         "evidence": "avatar_allin_text+investment_amount",
                         "investmentText": result.get("investmentText", "")}
                earliest_allin = next((item for item in self.action_ocr_trace
                                       if item.get("handId") == result.get("handId") and
                                       item.get("street") == result.get("street") and
                                       item.get("index") == result.get("index") and
                                       item.get("action") == "allin" and
                                       float(item.get("videoSecond") or float("inf")) <=
                                       float(result.get("videoSecond") or float("inf"))), None)
                if earliest_allin is not None:
                    event.update(videoSecond=earliest_allin.get("videoSecond"),
                                 observedAt=earliest_allin.get("videoSecond"),
                                 frameSequence=earliest_allin.get("frameSequence"))
                prior_actor_action = next((item for item in reversed(self.action_log)
                                           if item.get("handId") == event.get("handId") and
                                           item.get("street") == event.get("street") and
                                           item.get("seat") == event.get("seat") and
                                           item.get("action") in ("bet", "raise", "reraise")), None)
                reopened_after_prior = bool(
                    prior_actor_action and
                    self._action_reopened_after(self.action_log, prior_actor_action)
                )
                current_highest = max(
                    (float(item.get("amount") or 0) for item in self.action_log
                     if item.get("handId") == event.get("handId") and
                     item.get("street") == event.get("street") and
                     item.get("seat") != event.get("seat")),
                    default=0.0,
                )
                if (reopened_after_prior and bet not in (None, 0) and current_highest > 0 and
                        float(bet) < current_highest and prior_actor_action.get("amount") not in (None, 0)):
                    allin_increase = float(bet)
                    bet = round(float(prior_actor_action["amount"]) + allin_increase, 6)
                    event.update(amount=bet, increase=allin_increase,
                                 evidence="avatar_allin_text+remaining_stack_amount")
                prior_chips = float(prior_actor_action.get("chipsAfter") or 0) if prior_actor_action else 0
                prior_increase = float(prior_actor_action.get("increase") or 0) if prior_actor_action else 0
                remaining_stack = prior_chips - prior_increase
                stack_zero_confirmed = chips == 0
                stale_pre_action_stack = (chips == prior_chips and prior_increase > 0 and remaining_stack > 0)
                if (event.get("evidence") != "avatar_allin_text+remaining_stack_amount" and
                        reopened_after_prior and prior_actor_action.get("amount") not in (None, 0) and
                        (stack_zero_confirmed or stale_pre_action_stack)):
                    allin_increase = prior_chips if stack_zero_confirmed else remaining_stack
                    bet = round(float(prior_actor_action["amount"]) + allin_increase, 6)
                    event.update(amount=bet, increase=allin_increase, chipsAfter=0,
                                 evidence="avatar_allin_text+stack_reconciled")
                unresolved_allin = next((item for item in reversed(self.action_log)
                                         if item.get("handId") == event.get("handId") and
                                         item.get("street") == event.get("street") and
                                         item.get("seat") == event.get("seat") and
                                         item.get("action") == "allin" and
                                         item.get("amount") in (None, 0)), None)
                if unresolved_allin is not None and bet not in (None, 0):
                    unresolved_allin.update(amount=bet,
                                            increase=max(0.0, bet - float(tracker.get("stableBet") or 0)),
                                            investmentText=event.get("investmentText", ""),
                                            evidence="avatar_allin_text+investment_amount",
                                            confidence=max(float(unresolved_allin.get("confidence") or 0),
                                                           float(event.get("confidence") or 0)))
                    tracker["stableBet"] = bet
                    tracker["lastAction"] = "allin"
                    continue
                prior_same_amount = next((item for item in reversed(self.action_log)
                                          if item.get("handId") == event.get("handId") and
                                          item.get("street") == event.get("street") and
                                          item.get("seat") == event.get("seat") and
                                          item.get("action") in ("bet", "raise", "reraise") and
                                          item.get("amount") == event.get("amount")), None)
                if bet in (None, 0):
                    prior_same_amount = next((item for item in reversed(self.action_log)
                                              if item.get("handId") == event.get("handId") and
                                              item.get("street") == event.get("street") and
                                              item.get("seat") == event.get("seat") and
                                              item.get("action") in ("bet", "raise", "reraise") and
                                              float(item.get("amount") or 0) > 0), None)
                if prior_same_amount is not None and not reopened_after_prior:
                    prior_same_amount.update(action="allin", evidence=event["evidence"],
                                             confidence=max(float(prior_same_amount.get("confidence") or 0),
                                                            float(event.get("confidence") or 0)),
                                             investmentText=event.get("investmentText", ""))
                    tracker["lastAction"] = "allin"
                    continue
                if bet in (None, 0):
                    event.update(action="allin_amount_unresolved", visualCandidate=True,
                                 strategyEligible=False,
                                 evidence="avatar_allin_text+amount_unresolved")
                    self._append_action_candidate(event)
                    tracker["lastAction"] = "allin"
                    tracker["visualState"] = "allin"
                    self.action_unresolved_retries[result["index"]] = 3
                elif self._append_action_event(event):
                    for candidate in self.action_candidates:
                        if (candidate.get("handId") == event.get("handId") and
                                candidate.get("street") == event.get("street") and
                                candidate.get("seat") == event.get("seat") and
                                candidate.get("action") == "allin_amount_unresolved"):
                            candidate["promoted"] = True
                    tracker["stableBet"] = bet
                    tracker["lastAction"] = "allin"
                    events.append(event)
                continue
            if action == "straddle" and bet is not None and result.get("street") == "preflop":
                prior = next((item for item in reversed(self.action_log)
                              if item.get("handId") == result.get("handId") and
                              item.get("street") == "preflop" and
                              item.get("seat") == result.get("index") + 1 and
                              item.get("action") == "bet" and
                              abs(float(item.get("amount") or 0) - float(bet)) <= .01), None)
                if prior is not None:
                    prior.update(action="straddle", confidence=max(float(prior.get("confidence") or 0),
                                                                    float(result.get("confidence") or 0)),
                                 evidence="Straddle文字+投入金额",
                                 investmentText=result.get("investmentText", ""))
                    tracker["lastAction"] = "straddle"
                    self._advance_after_confirmed_straddle(result["index"], result.get("handId"))
                    continue
            if action == "straddle" and result.get("street") != "preflop":
                self.pending_hand_boundary_forced.append({
                    "observedAt": result.get("observedAt"), "videoSecond": result.get("videoSecond"),
                    "frameSequence": result.get("frameSequence"), "seat": result["index"] + 1,
                    "name": result.get("name", ""), "action": "straddle", "amount": bet,
                    "increase": bet, "chipsAfter": chips, "potAfter": pot_after,
                    "confidence": result.get("confidence", 0), "evidence": result.get("evidenceSource")})
                self.pending_hand_boundary_forced = self.pending_hand_boundary_forced[-8:]
                continue
            highest_other = max(
                (float(value.get("stableBet") or 0) for key, value in self.seat_trackers.items()
                 if key != result.get("index")), default=0.0)
            prior_actor_amount = max(
                float(tracker.get("stableBet") or 0),
                max((float(item.get("amount") or 0) for item in self.action_log
                     if item.get("handId") == result.get("handId") and
                     item.get("street") == result.get("street") and
                     item.get("seat") == result.get("index") + 1), default=0.0),
            )
            amount_tolerance = max(.01, highest_other * .02)
            if (action in ("bet", "raise", "reraise") and bet not in (None, 0) and
                    highest_other > 0 and float(bet) < highest_other - amount_tolerance):
                if abs(prior_actor_amount + float(bet) - highest_other) <= amount_tolerance:
                    action = "call"
                    bet = highest_other
                    result["investmentText"] = str(result.get("investmentText") or "")
                    result["evidenceSource"] = "displayed_increment+confirmed_call_price"
                else:
                    continue
            if (action in ("bet", "raise", "reraise") and result.get("text") == "color_investment" and
                    bet not in (None, 0) and highest_other > 0 and
                    abs(float(bet) - highest_other) <= .01):
                action = "call"
                if result.get("index") == getattr(self, "formal_expected_seat", None):
                    result["confidence"] = max(.9, float(result.get("confidence") or 0))
            if action in ("bet", "raise", "reraise") and bet not in (None, 0):
                prior_amount = prior_actor_amount
                prior_forced = next(
                    (item for item in reversed(self.action_log)
                     if item.get("handId") == result.get("handId") and
                     item.get("street") == "preflop" and
                     item.get("seat") == result.get("index") + 1 and
                     item.get("action") in ("blind", "post_blind", "straddle")),
                    None)
                if (prior_forced is not None and
                        float(bet) <= float(prior_forced.get("amount") or 0) + .001):
                    continue
                rule_confirmed_aggression = (
                    result.get("index") == getattr(self, "formal_expected_seat", None) and
                    result.get("text") != "color_investment" and
                    "$" in str(result.get("investmentText") or "") and
                    "." in str(result.get("investmentText") or "") and
                    float(bet) > highest_other + .01
                )
                event = {"time": result.get("recognizedAt", time.time()),
                         "observedAt": result.get("observedAt"),
                         "recognizedAt": result.get("recognizedAt"),
                         "videoSecond": result.get("videoSecond"),
                         "frameSequence": result.get("frameSequence"),
                         "handId": result.get("handId"), "street": result.get("street"),
                         "sequence": 1, "seat": result["index"] + 1,
                         "name": result.get("name", ""), "action": action, "amount": bet,
                         "increase": max(0.0, float(bet) - prior_amount),
                         "chipsAfter": chips, "potAfter": pot_after,
                         "confidence": (max(.9, float(result.get("confidence") or 0))
                                        if rule_confirmed_aggression else result.get("confidence", 0)),
                         "evidence": "明确动作文字+货币金额",
                         "investmentText": result.get("investmentText", ""),
                         "capsuleEpoch": result.get("capsuleEpoch")}
                if self._append_action_event(event):
                    tracker["stableBet"] = bet
                    tracker["lastAction"] = action
                    events.append(event)
                continue
            inferred_call_amount = None
            if bet is None and action == "call":
                inferred_call_amount = max(
                    (value.get("stableBet", 0.0) for key, value in self.seat_trackers.items()
                     if key != result.get("index")), default=0.0)
                logged_highest = max(
                    (float(item.get("amount") or 0) for item in self.action_log
                     if item.get("handId") == result.get("handId") and
                     item.get("street") == result.get("street") and
                     item.get("seat") != result.get("index") + 1 and
                     item.get("action") in ("bet", "raise", "reraise", "call", "allin")),
                    default=0.0)
                inferred_call_amount = max(inferred_call_amount, logged_highest)
                if inferred_call_amount <= 0:
                    inferred_call_amount = None
                else:
                    previous_bet = float(tracker.get("stableBet") or 0)
                    tracker["stableBet"] = inferred_call_amount
                    tracker["lastAction"] = "call"
            if bet is None and action in ("call", "bet", "raise", "straddle"):
                if action in ("bet", "raise") and result.get("text") == "color_investment":
                    continue
                event = {"time": result.get("recognizedAt", time.time()),
                         "observedAt": result.get("observedAt"), "recognizedAt": result.get("recognizedAt"),
                         "frameSequence": result.get("frameSequence"), "handId": result.get("handId"),
                         "street": result.get("street"), "sequence": 1, "seat": result["index"] + 1,
                         "name": result.get("name", ""), "action": action, "amount": inferred_call_amount,
                         "increase": (inferred_call_amount - previous_bet
                                      if inferred_call_amount is not None else None),
                         "chipsAfter": chips, "potAfter": pot_after,
                         "confidence": result.get("confidence", 0), "evidence": result.get("evidenceSource"),
                         "capsuleEpoch": result.get("capsuleEpoch"),
                         "queueLatencyMs": result.get("queueLatencyMs"),
                         "preEnqueueLatencyMs": result.get("preEnqueueLatencyMs"),
                         "actualQueueLatencyMs": result.get("actualQueueLatencyMs"),
                         "ocrDurationMs": result.get("ocrDurationMs")}
                if inferred_call_amount is not None:
                    event["evidence"] = "跟注文字+当前最高投入"
                    event["confidence"] = min(float(event["confidence"] or 0), .9)
                if event.get("amount") is None:
                    event.update(action=f"{action}_amount_unresolved", visualCandidate=True,
                                 confidence=min(float(event.get("confidence") or 0), .75),
                                 evidence=f"{event.get('evidence')}+amount_unresolved")
                    self._append_action_candidate(event)
                    self.action_unresolved_retries[result["index"]] = 3
                elif self._append_action_event(event):
                    events.append(event)
            elif (result.get("handId") == self.hand_state.get("id") and
                    result.get("street") == self.hand_state.get("street")):
                observation = {"index": result["index"], "name": result.get("name", ""),
                               "chips": chips, "streetBet": bet, "action": action,
                               "occupancy": "occupied", "observedAt": result.get("observedAt"),
                               "frameSequence": result.get("frameSequence"),
                               "evidenceSource": result.get("evidenceSource"),
                               "capsuleEpoch": result.get("capsuleEpoch"),
                               "investmentText": result.get("investmentText", ""),
                               "recognizedAt": result.get("recognizedAt"),
                               "queueLatencyMs": result.get("queueLatencyMs"),
                               "preEnqueueLatencyMs": result.get("preEnqueueLatencyMs"),
                               "actualQueueLatencyMs": result.get("actualQueueLatencyMs"),
                               "ocrDurationMs": result.get("ocrDurationMs")}
                _, confirmed = self._update_action_state([observation], pot_after=pot_after)
                events.extend(confirmed)
            else:
                event = {"time": result.get("recognizedAt", time.time()), "observedAt": result.get("observedAt"),
                         "recognizedAt": result.get("recognizedAt"), "frameSequence": result.get("frameSequence"),
                         "handId": result.get("handId"), "street": result.get("street"), "sequence": 1,
                         "seat": result["index"] + 1, "name": result.get("name", ""), "action": action,
                         "amount": bet, "increase": None, "chipsAfter": chips, "potAfter": pot_after,
                         "confidence": result.get("confidence", 0), "evidence": result.get("evidenceSource"),
                         "capsuleEpoch": result.get("capsuleEpoch")}
                if self._append_action_event(event):
                    events.append(event)
        return events

    def _is_delayed_prior_street_result(self, result):
        if result.get("handId") != self.hand_state.get("id"):
            return False
        order = {"preflop": 0, "flop": 1, "turn": 2, "river": 3}
        captured = order.get(result.get("capturedStreet", result.get("street")))
        current = order.get(self.hand_state.get("street"))
        return captured is not None and current is not None and captured < current

    def _record_delayed_prior_street_result(self, result, tracker):
        action = result.get("action")
        avatar_state = result.get("avatarState")
        if avatar_state in ("fold", "allin"):
            action = avatar_state
        amount = result.get("bet")
        if action in ("fold", "check"):
            amount = 0.0
        elif action == "call" and amount in (None, 0):
            amount = result.get("highestBetAtCapture")
        if action == "allin" and amount in (None, 0):
            return self._promote_persistent_allin_to_prior_street(result, tracker)
        if action not in ("fold", "check", "call", "bet", "raise", "reraise", "allin"):
            return False
        if action in ("call", "bet", "raise", "reraise", "allin") and amount in (None, 0):
            return False
        prior_amount = float(result.get("actorBetAtCapture") or 0)
        event = {
            "time": result.get("recognizedAt", time.time()),
            "observedAt": result.get("capturedObservedAt", result.get("observedAt")),
            "recognizedAt": result.get("recognizedAt", time.time()),
            "videoSecond": result.get("videoSecond"),
            "frameSequence": result.get("capturedFrameSequence", result.get("frameSequence")),
            "handId": result.get("capturedHandId", result.get("handId")),
            "street": result.get("capturedStreet", result.get("street")),
            "sequence": 1, "seat": result.get("index") + 1,
            "name": result.get("name", ""), "action": action, "amount": amount,
            "increase": (0.0 if action in ("fold", "check") else
                         max(0.0, float(amount) - prior_amount)),
            "chipsAfter": result.get("chips"), "potAfter": result.get("potAfter"),
            "confidence": result.get("confidence", 0),
            "evidence": f"{result.get('evidenceSource') or 'action_ocr'}+delayed_captured_frame",
            "investmentText": result.get("investmentText", ""),
            "capsuleEpoch": result.get("capsuleEpoch"),
            "queueLatencyMs": result.get("queueLatencyMs"),
            "preEnqueueLatencyMs": result.get("preEnqueueLatencyMs"),
            "actualQueueLatencyMs": result.get("actualQueueLatencyMs"),
            "ocrDurationMs": result.get("ocrDurationMs"),
            "capturedActionRound": result.get("capturedActionRound"),
            "capturedTimeWindowId": result.get("capturedTimeWindowId"),
        }
        current_expected = self.formal_expected_seat
        forced_window = self.waiting_for_forced_bets
        tracker_state = {key: tracker.get(key) for key in ("lastAction", "stableBet")}
        accepted = self._append_action_event(event, resolve_prior=False)
        self.formal_expected_seat = current_expected
        self.waiting_for_forced_bets = forced_window
        if action not in ("fold", "allin"):
            tracker.update(tracker_state)
        else:
            tracker["lastAction"] = action
        prior = getattr(self, "prior_street_unresolved", None)
        if accepted and prior and prior.get("street") == event["street"]:
            prior.get("seats", set()).discard(result.get("index"))
        return accepted

    def _promote_persistent_allin_to_prior_street(self, result, tracker):
        action = result.get("action")
        if result.get("avatarState") == "allin":
            action = "allin"
        if action != "allin" or result.get("bet") not in (None, 0):
            return False
        unresolved = getattr(self, "prior_street_unresolved", None)
        if (not unresolved or result.get("index") not in unresolved.get("seats", set())):
            return False
        street_order = {"preflop": 0, "flop": 1, "turn": 2, "river": 3}
        captured_street = result.get("capturedStreet", result.get("street"))
        captured_is_prior = (street_order.get(captured_street, -1) <
                             street_order.get(self.hand_state.get("street"), -1))
        if result.get("capsuleDetected") and not captured_is_prior:
            return False
        hand_id = result.get("handId")
        current_street = self.hand_state.get("street")
        current_investment = any(
            item.get("handId") == hand_id and item.get("street") == current_street and
            item.get("seat") == result.get("index") + 1 and
            item.get("action") in ("call", "bet", "raise", "reraise", "allin") and
            float(item.get("amount") or 0) > 0
            for item in self.action_log
        )
        if current_investment:
            return False
        current_order = street_order.get(current_street, -1)
        prior_event = next((
            item for item in reversed(self.action_log)
            if item.get("handId") == hand_id and item.get("seat") == result.get("index") + 1 and
            street_order.get(item.get("street"), -1) < current_order and
            item.get("action") in ("call", "bet", "raise", "reraise") and
            float(item.get("amount") or 0) > 0
        ), None)
        if prior_event is None:
            return False
        if prior_event.get("street") != unresolved.get("street"):
            if not prior_event.get("orderConflict"):
                return False
            later_actor_action = any(
                item is not prior_event and item.get("handId") == hand_id and
                item.get("seat") == result.get("index") + 1 and
                street_order.get(prior_event.get("street"), -1) <
                street_order.get(item.get("street"), -1) < current_order and
                item.get("action") not in ("blind", "post_blind", "straddle")
                for item in self.action_log
            )
            if later_actor_action:
                return False
        if prior_event.get("orderConflict") and unresolved.get("changedAt") is not None:
            prior_event["rawObservedAt"] = prior_event.get("observedAt")
            prior_event["rawVideoSecond"] = prior_event.get("videoSecond")
            prior_event["observedAt"] = unresolved["changedAt"]
            prior_event["videoSecond"] = unresolved["changedAt"]
            prior_event["timeAdjustedByStreetBoundary"] = True
        prior_event.update(
            action="allin",
            confidence=max(float(prior_event.get("confidence") or 0),
                           float(result.get("confidence") or 0)),
            evidence=f"{prior_event.get('evidence') or 'investment_action'}+later_persistent_allin_badge",
            terminalConfirmedAt=result.get("recognizedAt", time.time()),
            terminalConfirmedFrame=result.get("frameSequence"),
        )
        tracker["lastAction"] = "allin"
        prior = getattr(self, "prior_street_unresolved", None)
        if prior and prior.get("street") == prior_event.get("street"):
            prior.get("seats", set()).discard(result.get("index"))
        ActionLedgerLayer.reorder(
            self.action_log, getattr(self, "hand_dealers", {}), self.hand_participants,
            self.hand_dealer_index, len(TABLE_LAYOUTS[self.layout]))
        self._publish_confirmed_action_state(prior_event)
        self._publish_action_audit(prior_event)
        return True

    def _discard_action_ocr_results(self):
        discarded = 0
        while True:
            try:
                self.action_ocr_results.get_nowait()
                discarded += 1
            except queue.Empty:
                return discarded

    def _action_timeline_boundary(self, observed_at=None, frame_sequence=None,
                                  video_second=None):
        recording_second = getattr(self, "recording_second", None)
        if video_second is None:
            video_second = recording_second
        if (recording_second is not None and isinstance(observed_at, (int, float)) and
                observed_at < 1_000_000_000):
            video_second = observed_at
            observed_at = None
        if observed_at is None:
            captured_at = getattr(self, "latest_frame_captured_at", None)
            observed_at = captured_at if captured_at is not None else time.time()
        if frame_sequence is None:
            frame_sequence = getattr(self, "latest_frame_sequence", 0)
        return observed_at, frame_sequence, video_second

    def _start_action_timeline(self, hand_id, observed_at=None, frame_sequence=None,
                               video_second=None):
        boundary = self._action_timeline_boundary(
            observed_at, frame_sequence, video_second)
        started = self.action_timeline.start_hand(hand_id, *boundary)
        if started:
            self._write_action_timeline_audit("hand_started")
        return started

    def _transition_action_timeline(self, hand_id, from_street, to_street,
                                    observed_at=None, frame_sequence=None,
                                    video_second=None):
        boundary = self._action_timeline_boundary(
            observed_at, frame_sequence, video_second)
        self.action_timeline.transition_street(
            hand_id, from_street, to_street, *boundary)
        self._write_action_timeline_audit(
            "street_changed", fromStreet=from_street, toStreet=to_street)

    def _rebuild_action_timeline(self, hand_id, street, event=None):
        timeline = getattr(self, "action_timeline", None)
        if timeline is None:
            return None
        if not timeline.current or timeline.current.get("handId") != hand_id:
            self._start_action_timeline(hand_id)
        street_item = timeline.rebuild(self.action_log, hand_id, street)
        if event is not None:
            ordered = next((item for item in self.action_log
                            if item.get("handId") == event.get("handId") and
                            item.get("street") == event.get("street") and
                            item.get("seat") == event.get("seat") and
                            item.get("action") == event.get("action") and
                            self._event_second(item) == self._event_second(event)), None)
            if ordered:
                for key in ("actionRound", "timeWindowId", "timeMatchedActionRound",
                            "timeWindowConflict", "priorHighestBet"):
                    if key in ordered:
                        event[key] = ordered[key]
        self._write_action_timeline_audit(
            "action_confirmed", event=event, streetWindow=street_item)
        return street_item

    def _close_action_timeline(self, reason, observed_at=None, frame_sequence=None,
                               video_second=None):
        timeline = getattr(self, "action_timeline", None)
        if timeline is None or not timeline.current:
            return None
        boundary = self._action_timeline_boundary(
            observed_at, frame_sequence, video_second)
        snapshot = timeline.close_hand(*boundary)
        self._write_action_timeline_audit(reason, timeline=snapshot)
        return snapshot

    def _write_action_timeline_audit(self, kind, timeline=None, **details):
        path = getattr(self, "action_timeline_audit_file", None)
        if path is None:
            return
        event = details.get("event")
        if isinstance(event, dict):
            details["event"] = {key: event.get(key) for key in (
                "handId", "street", "actionRound", "capturedActionRound",
                "timeMatchedActionRound", "timeWindowId", "capturedTimeWindowId",
                "timeWindowConflict", "seat", "action", "amount", "observedAt",
                "recognizedAt", "confirmedAt", "frameSequence", "videoSecond",
            ) if key in event}
        record = {
            "type": kind, "recordedAt": time.time(), "appVersion": APP_VERSION,
            "runtimeId": self.runtime_id,
            "timeline": timeline if timeline is not None else self.action_timeline.snapshot(),
            **details,
        }
        self._rotate_log_if_needed(
            path, self.audit_log_max_bytes, self.audit_log_backup_count)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def _compare_shadow_action_engine(self, event, production_chain):
        try:
            hand_id = event.get("handId")
            street = event.get("street")
            streets = ("preflop", "flop", "turn", "river")
            current = [item for item in self.action_log
                       if item.get("handId") == hand_id and
                       streets.index(item.get("street", "preflop")) <= streets.index(street)]
            exclusion = self.shadow_action_engine.batch_a_exclusion(event)
            if exclusion is None:
                prior_exclusion = self.shadow_action_engine.prior_batch_a_exclusion(
                    current[:-1])
                if prior_exclusion is not None:
                    exclusion = f"prior_{prior_exclusion}"
            evidence = None
            accepted = False
            if exclusion is None:
                participants = self.hand_participants.get(hand_id)
                if participants is None:
                    participants = self._current_hand_eligible_indices()
                ordinary = [item for item in current
                            if self.shadow_action_engine.batch_a_exclusion(item) is None]
                self.shadow_action_engine.replace_confirmed_actions(
                    ordinary, self.runtime_id, self.table_session, hand_id)
                evidence = EvidenceEvent.from_confirmed_action(
                    event, self.runtime_id, self.table_session)
                accepted = True
                batch_b_result = self.batch_b_action_engine.rebuild(
                    ordinary, self.hand_dealers.get(hand_id, self.hand_dealer_index),
                    participants, len(TABLE_LAYOUTS[self.layout]), hand_id, street)
                shadow_chain = batch_b_result.get("snapshot")
                if shadow_chain is None:
                    shadow_chain = self.shadow_action_engine.snapshot(
                        self.hand_dealers.get(hand_id, self.hand_dealer_index),
                        participants, len(TABLE_LAYOUTS[self.layout]), hand_id, street)
                comparison = self.shadow_action_engine.compare(production_chain, shadow_chain)
                status = "matched" if comparison["matched"] else "different"
            else:
                comparison = {"matched": None, "differences": {}}
                status = "excluded"
            record = {
                "schemaVersion": 1,
                "mode": "read_only_shadow",
                "batch": "phase2-a",
                "migrationBatch": "phase2-b",
                "status": status,
                "exclusionReason": exclusion,
                "accepted": accepted,
                "recordedAt": time.time(),
                "runtimeId": self.runtime_id,
                "tableSession": self.table_session,
                "handId": hand_id,
                "street": street,
                "seat": event.get("seat"),
                "action": event.get("action"),
                "evidence": evidence.as_record() if evidence is not None else None,
                **comparison,
            }
            self._rotate_log_if_needed(
                self.action_engine_shadow_file, self.audit_log_max_bytes,
                self.audit_log_backup_count)
            with self.action_engine_shadow_file.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except Exception as error:
            self._write_action_timeline_audit(
                "shadow_action_engine_error", event=event,
                error=f"{type(error).__name__}: {error}")

    def _commit_formal_action_ledger(self, event):
        if getattr(self, "action_engine_mode", "formal") == "legacy":
            ActionLedgerLayer.reorder(
                self.action_log, getattr(self, "hand_dealers", {}),
                self.hand_participants, self.hand_dealer_index,
                len(TABLE_LAYOUTS[self.layout]))
            self.action_engine_status = "legacy_explicit_fallback"
            return {"status": self.action_engine_status,
                    "snapshot": self._action_chain_snapshot(
                        event.get("handId"), event.get("street"))}
        hand_id = event.get("handId")
        participants = self.hand_participants.get(hand_id)
        if not participants:
            participants = self._current_hand_eligible_indices()
        participants = set(participants or ())
        active_action_seats = {
            int(item["seat"]) - 1 for item in self.action_log
            if item.get("handId") == hand_id and item.get("seat") and
            item.get("action") not in ("fold", "allin")
        }
        pending_terminal_seats = {
            int(item["seat"]) - 1 for item in getattr(self, "action_candidates", ())
            if item.get("handId") == hand_id and
            item.get("street") == event.get("street") and item.get("seat") and
            item.get("action") in ("fold", "allin") and
            not item.get("promoted") and not item.get("expired")
        }
        preserved_seats = active_action_seats | pending_terminal_seats
        participants.difference_update(
            index for index, tracker in self.seat_trackers.items()
            if tracker.get("lastAction") in ("fold", "allin") and
            index not in preserved_seats
        )
        hand_dealers = getattr(self, "hand_dealers", {})
        result = ActionEngine.commit(
            self.action_log,
            hand_dealers.get(hand_id, self.hand_dealer_index),
            participants, len(TABLE_LAYOUTS[self.layout]), hand_id,
            event.get("street"), getattr(self, "blind_amounts", {}).get("big"))
        self.action_engine_status = result["status"]
        if result["status"] != "rejected":
            self._action_event_ledger().sync_projection(
                self.action_log, "formal_action_commit")
        return result

    def _action_event_ledger(self):
        store = getattr(self, "action_event_store", None)
        if store is None:
            data_dir = getattr(self, "data_dir", None)
            store = ActionEventStore(
                Path(data_dir) / "action-event-ledger.jsonl" if data_dir else None)
            self.action_event_store = store
        return store

    def _betting_round_closed(self, hand_id=None, street=None):
        hand_id = self.hand_state.get("id") if hand_id is None else hand_id
        street = self.hand_state.get("street") if street is None else street
        if street not in ("preflop", "flop", "turn", "river"):
            return False
        events = [item for item in self.action_log
                  if item.get("handId") == hand_id and item.get("street") == street and
                  item.get("action") not in ("blind", "post_blind", "straddle")]
        participants = self.hand_participants.get(hand_id)
        active = {index + 1 for index, tracker in self.seat_trackers.items()
                  if (not participants or index in participants) and
                  tracker.get("occupancy") == "occupied" and
                  tracker.get("lastAction") not in ("fold", "allin")}
        if not active or not events:
            return False
        latest_by_seat = {seat: next((item for item in reversed(events) if item.get("seat") == seat), None)
                          for seat in active}
        if any(item is None for item in latest_by_seat.values()):
            return False
        aggressive = [item for item in events if item.get("action") in ("bet", "raise", "reraise", "allin")]
        if not aggressive:
            allowed = ("check", "call") if street == "preflop" else ("check",)
            return all(item.get("action") in allowed for item in latest_by_seat.values())
        last_aggressive = aggressive[-1]
        try:
            aggressive_index = events.index(last_aggressive)
        except ValueError:
            return False
        acted_after = {item.get("seat") for item in events[aggressive_index:]}
        return active.issubset(acted_after) and all(
            item.get("action") in ("call", "allin") or seat == last_aggressive.get("seat")
            for seat, item in latest_by_seat.items()
        )

    def _action_chain_snapshot(self, hand_id=None, street=None):
        hand_id = self.hand_state.get("id") if hand_id is None else hand_id
        street = self.hand_state.get("street") if street is None else street
        participants = (self._current_hand_eligible_indices()
                        if hand_id == self.hand_state.get("id") else
                        self.hand_participants.get(hand_id))
        participants = set(participants or ())
        participants.update(
            int(item["seat"]) - 1
            for item in self.action_log
            if item.get("handId") == hand_id and
            item.get("action") in ("fold", "allin") and
            item.get("seat") and not item.get("visualCandidate") and
            not str(item.get("action", "")).endswith("_unresolved")
        )
        if not participants:
            participants = {
                index for index, tracker in self.seat_trackers.items()
                if tracker.get("occupancy") == "occupied" and
                tracker.get("handEligible", True)
            }
        dealer = getattr(self, "hand_dealers", {}).get(
            hand_id, getattr(self, "hand_dealer_index", None))
        return ActionChainEngine.rebuild(
            self.action_log, dealer, participants,
            len(TABLE_LAYOUTS[self.layout]), hand_id=hand_id, street=street)

    def _mark_pipeline(self, kind, **details):
        item = {"kind": kind, "at": time.perf_counter(), **details}
        if not hasattr(self, "pipeline_timestamps"):
            self.pipeline_timestamps = deque(maxlen=500)
        self.pipeline_timestamps.append(item)
        return item

    def frame_buffer_status(self):
        with self.frame_buffer_lock:
            return CaptureLayer.status(self.frame_buffer, self.frame_buffer_dropped,
                                       self.frame_buffer_queue.qsize())

    def _card_recognition_loop(self):
        previous_sequence = -1
        while True:
            started = time.time()
            try:
                with self.capture_lock:
                    frame = self.latest_table_frame.copy() if self.latest_table_frame is not None else None
                    sequence = self.latest_frame_sequence
                    captured_at = self.latest_frame_captured_at
                if frame is not None and sequence != previous_sequence:
                    previous_sequence = sequence
                    height, width = frame.shape[:2]
                    special_scene = self._detect_special_scene(frame)
                    self._observe_profile_scene(frame, captured_at, special_scene)
                    dealer_scene_blocked = self._gate_dealer_monitor_for_scene(special_scene)
                    if not dealer_scene_blocked:
                        self._monitor_dealer_frame(frame, captured_at, sequence)
                    card_hand_id = self.hand_state.get("id", 0)
                    if special_scene:
                        with self.card_state_lock:
                            self.card_visible["heroCards"] = []
                            self.card_visible["boardCards"] = []
                            self.card_visible_frame_sequence = sequence
                        if special_scene == "lucky_impact":
                            self.dealer_blocked_until_board_clear = True
                        with self.state_lock:
                            self.cached_state = dict(self.cached_state or {})
                            self.cached_state["specialScene"] = special_scene
                        continue
                    with self.state_lock:
                        self.cached_state = dict(self.cached_state or {})
                        self.cached_state["specialScene"] = None
                    hero_box = self._reviewed_slot_box((315, 1570, 575, 1745), width, height)
                    hero_region = frame[hero_box[1]:hero_box[3], hero_box[0]:hero_box[2]]
                    board_region = frame[int(height * .38):int(height * .62), int(width * .18):int(width * .82)]
                    self._card_recognition_field = "heroCards"
                    hero_cards = self._recognize_cards_fast(hero_region)[:2]
                    self._card_recognition_field = "boardCards"
                    board_cards = self._recognize_board_card_slots(frame, board_region)
                    self._card_recognition_field = "unknown"
                    hero_cards = hero_cards if len(hero_cards) == 2 else []
                    board_cards = board_cards if len(board_cards) in (0, 3, 4, 5) else []
                    with self.card_state_lock:
                        self.card_visible["heroCards"] = list(hero_cards)
                        self.card_visible["boardCards"] = list(board_cards)
                        self.card_visible_frame_sequence = sequence
                    self._commit_card_observation(
                        "heroCards", hero_cards, captured_at, frame_sequence=sequence,
                        hand_id=card_hand_id)
                    board_changed = self._commit_card_observation(
                        "boardCards", board_cards, captured_at, frame_sequence=sequence,
                        hand_id=card_hand_id)
                    if board_changed and board_cards:
                        self._sync_fast_street(board_cards)
            except Exception as error:
                self.fields.commit("cardChannel", str(error), 0, "cards", False)
            time.sleep(max(0.005, .015 - (time.time() - started)))

    def _commit_card_observation(self, field, cards, captured_at=None, allow_empty=False,
                                 frame_sequence=None, hand_id=None):
        cards = list(cards or [])
        card_state_lock = getattr(self, "card_state_lock", None)
        if card_state_lock is None:
            card_state_lock = self.card_state_lock = threading.RLock()
        with card_state_lock:
            current_hand_id = self.hand_state.get("id", 0)
            if hand_id is not None and hand_id != current_hand_id:
                return False
            if frame_sequence is not None:
                last_sequences = getattr(self, "card_last_frame_sequence", None)
                if last_sequences is None:
                    last_sequences = self.card_last_frame_sequence = {
                        "heroCards": -1, "boardCards": -1}
                if frame_sequence <= last_sequences.get(field, -1):
                    return False
                last_sequences[field] = frame_sequence
            published = list(self.card_published.get(field, []))
            allowed, _ = CardStateLayer.candidate_allowed(
                field, cards, published, allow_empty=allow_empty)
            if not allowed:
                return False
            if cards == self.card_candidates[field]:
                self.card_candidate_frames[field] += 1
            else:
                self.card_candidates[field] = cards
                self.card_candidate_frames[field] = 1
            required_frames = CardStateLayer.required_frames(field, cards, allow_empty)
            if self.card_candidate_frames[field] < required_frames:
                return False
            self.card_published[field] = cards
        recognized_at = time.time()
        latency_ms = (round(max(0, recognized_at - captured_at) * 1000, 1)
                      if captured_at and abs(recognized_at - captured_at) < 60 else None)
        if not hasattr(self, "card_publish_trace"):
            self.card_publish_trace = deque(maxlen=500)
        self.card_publish_trace.append({"field": field, "cards": list(cards),
                                        "videoSecond": getattr(self, "recording_second", None),
                                        "capturedAt": captured_at,
                                        "recognizedAt": recognized_at,
                                        "latencyMs": latency_ms})
        diagnostic_file = getattr(self, "card_diagnostic_file", None)
        try:
            if not diagnostic_file:
                raise OSError
            self._append_bounded_audit(diagnostic_file, {
                "type": "published", "appVersion": APP_VERSION,
                "field": field, "cards": list(cards),
                "handId": self.hand_state.get("id", 0),
                "handKey": f"{getattr(self.history_store, 'session_id', 'session')}-{self.hand_state.get('id', 0)}",
                "videoSecond": getattr(self, "recording_second", None),
                "capturedAt": captured_at, "recognizedAt": recognized_at,
                "latencyMs": latency_ms})
        except OSError:
            pass
        with self.state_lock:
            self.cached_state = dict(self.cached_state or {})
            self.cached_state[field] = cards
            self.cached_state["cardUpdatedAt"] = recognized_at
            self.cached_state["cardFrameCapturedAt"] = captured_at
            self.cached_state["cardFrameSequence"] = frame_sequence
            self.cached_state["cardLatencyMs"] = latency_ms
        self.fields.commit(field, cards, .98, "cards", True)
        if field == "heroCards" and cards:
            self.hero_cards_present = True
            self.locked_hero_cards = cards
            self.locked_hero_hand_id = self.hand_state.get("id", 0)
            evidence = dict(getattr(self, "hero_evidence", {}))
            evidence.update(cards=True, cardsReliable=len(cards) == 2)
            self.hero_evidence = evidence
            self.participating_locked = len(cards) == 2 or self.participating_locked
            if len(cards) == 2:
                self.leave_evidence_frames = 0
                hand_id = self.hand_state.get("id", 0)
                hero_index = 3 if getattr(self, "layout", "8max") == "6max" else 4
                participants_by_hand = getattr(self, "hand_participants", None)
                participants = (participants_by_hand.setdefault(hand_id, set())
                                if isinstance(participants_by_hand, dict) else None)
                tracker = getattr(self, "seat_trackers", {}).get(hero_index)
                participant_restored = participants is not None and hero_index not in participants
                if participants is not None:
                    participants.add(hero_index)
                if tracker is not None:
                    tracker["handEligible"] = True
                    tracker.pop("excludedDuringHandId", None)
                    tracker.pop("excludedObservedAt", None)
                if participant_restored and any(
                        item.get("handId") == hand_id for item in self.action_log):
                    self._commit_formal_action_ledger({
                        "handId": hand_id,
                        "street": self.hand_state.get("street"),
                    })
        return True

    def _clear_dealer_monitor_transient_state(self):
        self.dealer_monitor_missing_at = None
        self.dealer_monitor_candidate = None
        self.dealer_monitor_candidate_frames = 0
        self.dealer_monitor_candidate_at = None

    def _gate_dealer_monitor_for_scene(self, special_scene):
        if special_scene:
            if not self.dealer_monitor_scene_blocked:
                self._clear_dealer_monitor_transient_state()
            self.dealer_monitor_scene_blocked = True
            return True
        if self.dealer_monitor_scene_blocked:
            self._clear_dealer_monitor_transient_state()
            self.dealer_monitor_scene_blocked = False
            return True
        return False

    def _monitor_dealer_frame(self, frame, captured_at, sequence):
        if self.dealer_blocked_until_board_clear:
            height, width = frame.shape[:2]
            board_region = frame[int(height * .38):int(height * .62),
                                 int(width * .18):int(width * .82)]
            board_shape = self._count_card_boxes(board_region)
            if board_shape > 0:
                self.dealer_board_clear_since = None
                return None
            board_cards = self._recognize_cards_fast(board_region)
            if board_cards:
                self.dealer_board_clear_since = None
                return None
            now = captured_at if isinstance(captured_at, (int, float)) else time.time()
            if self.dealer_board_clear_since is None:
                self.dealer_board_clear_since = now
                return None
            if now - self.dealer_board_clear_since < .75:
                return None
            self.dealer_blocked_until_board_clear = False
            self.dealer_board_clear_since = None
            with self.card_state_lock:
                self.card_published["boardCards"] = []
                self.card_candidates["boardCards"] = []
                self.card_candidate_frames["boardCards"] = 0
                self.card_last_frame_sequence["boardCards"] = sequence
            self.hand_state["boardCards"] = []
            with self.state_lock:
                self.cached_state = dict(self.cached_state or {})
                self.cached_state["boardCards"] = []
                self.cached_state["visibleBoardCards"] = []

        if not self.dealer_blocked_until_board_clear and self.card_published.get("boardCards"):
            height, width = frame.shape[:2]
            board_region = frame[int(height * .38):int(height * .62),
                                 int(width * .18):int(width * .82)]
            board_shape = self._count_card_boxes(board_region)
            board_cards = self._recognize_cards_fast(board_region)
            if board_shape <= 0 and not board_cards:
                self.dealer_stale_board_frames += 1
                if self.dealer_stale_board_frames >= 3:
                    with self.card_state_lock:
                        self.card_published["boardCards"] = []
                        self.card_visible["boardCards"] = []
                        self.card_candidates["boardCards"] = []
                        self.card_candidate_frames["boardCards"] = 0
                    with self.state_lock:
                        self.cached_state = dict(self.cached_state or {})
                        self.cached_state["boardCards"] = []
                        self.cached_state["visibleBoardCards"] = []
                    return None
            else:
                self.dealer_stale_board_pending = False
                self.dealer_stale_board_frames = 0
        else:
            self.dealer_stale_board_pending = False
            self.dealer_stale_board_frames = 0

        current = self.dealer_monitor_current
        if current is None:
            observed = self._observe_dealer_for_monitor(frame)
            if observed is None:
                return None
            if observed == self.dealer_monitor_candidate:
                self.dealer_monitor_candidate_frames += 1
            else:
                self.dealer_monitor_candidate = observed
                self.dealer_monitor_candidate_frames = 1
                self.dealer_monitor_candidate_at = captured_at
            if self.dealer_monitor_candidate_frames >= 2:
                self.dealer_monitor_current = observed
                self.dealer_monitor_candidate = None
                self.dealer_monitor_candidate_frames = 0
                if self.hand_machine.hand_id <= 0:
                    self._start_hand_from_fast_dealer(
                        observed, boundary_at=self.dealer_monitor_candidate_at or captured_at)
                elif self.hand_dealer_index is None:
                    self.hand_dealer_index = observed
                    self.hand_dealers[self.hand_machine.hand_id] = observed
                    self.formal_expected_seat = self._next_tracker_seat(
                        self._next_tracker_seat(observed))
            return None
        observed = self._observe_dealer_for_monitor(frame)
        current_present, current_score = self._dealer_present_in_slot(frame, current)
        resynchronized = False
        if current_present:
            self.dealer_monitor_missing_at = None
            if observed is None or observed == current:
                self.dealer_monitor_candidate = None
                self.dealer_monitor_candidate_frames = 0
                return None
            _, next_score = self._dealer_present_in_slot(frame, observed)
            if next_score < max(.35, current_score + .18):
                self.dealer_monitor_candidate = None
                self.dealer_monitor_candidate_frames = 0
                return None
            if observed == self.dealer_monitor_candidate:
                self.dealer_monitor_candidate_frames += 1
            else:
                self.dealer_monitor_candidate = observed
                self.dealer_monitor_candidate_frames = 1
                self.dealer_monitor_candidate_at = captured_at
            if self.dealer_monitor_candidate_frames < 3:
                return None
            resynchronized = True
        else:
            if self.dealer_monitor_missing_at is None:
                self.dealer_monitor_missing_at = captured_at
            if observed is None or observed == current:
                self.dealer_monitor_candidate = None
                self.dealer_monitor_candidate_frames = 0
                return None
            _, next_score = self._dealer_present_in_slot(frame, observed)
            if not self._dealer_transition_allowed(current, observed):
                if observed == self.dealer_monitor_candidate:
                    self.dealer_monitor_candidate_frames += 1
                else:
                    self.dealer_monitor_candidate = observed
                    self.dealer_monitor_candidate_frames = 1
                    self.dealer_monitor_candidate_at = captured_at
                if self.dealer_monitor_candidate_frames < 3:
                    return None
                resynchronized = True
        candidate_at = captured_at
        missing_at = self.dealer_monitor_missing_at
        started_at = (self.dealer_monitor_candidate_at if resynchronized else
                      missing_at if missing_at is not None and candidate_at - missing_at <= .15 else
                      candidate_at)
        event = {"from": current + 1, "to": observed + 1, "observedAt": started_at,
                 "confirmedAt": captured_at, "latencyMs": round(max(0, captured_at - started_at) * 1000, 1),
                 "candidateAppearedAt": candidate_at,
                 "confirmationLatencyMs": round(max(0, captured_at - candidate_at) * 1000, 1),
                 "frameSequence": sequence, "oldScore": round(current_score, 3),
                 "newScore": round(next_score, 3), "resynchronized": resynchronized}
        self.dealer_monitor_events.append(event)
        self.dealer_monitor_current = observed
        self.dealer_monitor_missing_at = None
        self.dealer_monitor_candidate = None
        self.dealer_monitor_candidate_frames = 0
        self._mark_pipeline("dealer_changed", **event)
        self._start_hand_from_fast_dealer(observed, boundary_at=started_at)
        return event

    def _observe_dealer_for_monitor(self, frame):
        try:
            return self._observe_dealer_anchors(frame, strict=True)
        except TypeError as error:
            if "strict" not in str(error):
                raise
            return self._observe_dealer_anchors(frame)

    def _dealer_transition_allowed(self, current, observed):
        if observed == current:
            return False
        if observed == self._next_dealer_monitor_seat(current):
            return True
        seat_count = len(TABLE_LAYOUTS[self.layout])
        if not self.hand_state.get("id") or (observed - current) % seat_count != 2:
            return False
        skipped = (current + 1) % seat_count
        hand_id = self.hand_state.get("id")
        if hand_id not in self.hand_participants:
            return False
        tracker = self.seat_trackers.get(skipped)
        participants = self.hand_participants.get(hand_id, set())
        if skipped not in participants:
            return True
        if tracker is None:
            return False
        if tracker.get("occupancy") == "empty":
            return True
        if tracker.get("handEligible") is False:
            return True
        if tracker.get("visualState") in ("away", "waiting", "empty"):
            return True
        return False

    def _next_dealer_monitor_seat(self, current):
        seat_count = len(TABLE_LAYOUTS[self.layout])
        for offset in range(1, seat_count + 1):
            candidate = (current + offset) % seat_count
            tracker = self.seat_trackers.get(candidate, {})
            if (tracker.get("occupancy") == "empty" and not tracker.get("name") and
                    tracker.get("chips") is None):
                continue
            return candidate
        return (current + 1) % seat_count

    def _dealer_present_in_slot(self, frame, index):
        height, width = frame.shape[:2]
        box = self._dealer_slot_box(index, width, height)
        if not box:
            return False, 0.0
        anchor_x, anchor_y = DEALER_ANCHORS[self.layout][index]
        center_x, center_y = int(anchor_x * width), int(anchor_y * height)
        if not (box[0] <= center_x <= box[2] and box[1] <= center_y <= box[3]):
            return False, 0.0
        radius = max(10, int(width * .029))
        anchor_patch = frame[max(0, center_y - radius):min(height, center_y + radius),
                             max(0, center_x - radius):min(width, center_x + radius)]
        if not anchor_patch.size:
            return False, 0.0
        anchor_hsv = cv2.cvtColor(anchor_patch, cv2.COLOR_BGR2HSV)
        white_ratio = float(np.mean((anchor_hsv[:, :, 1] < 120) &
                                    (anchor_hsv[:, :, 2] > 180)))
        dark_ratio = float(np.mean(anchor_hsv[:, :, 2] < 90))
        anchor_score = white_ratio + dark_ratio * .35
        if white_ratio >= .12 and .025 <= dark_ratio <= .30:
            return True, anchor_score
        x1, y1, x2, y2 = box
        patch = frame[max(0, y1):min(height, y2), max(0, x1):min(width, x2)]
        if not patch.size:
            return False, 0.0
        hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
        bright = ((hsv[:, :, 1] < 105) & (hsv[:, :, 2] > 185)).astype(np.uint8) * 255
        count, _, stats, _ = cv2.connectedComponentsWithStats(bright)
        best = 0.0
        for component in range(1, count):
            x, y, component_width, component_height, area = stats[component]
            if not (width * .018 <= component_width <= width * .065 and
                    height * .009 <= component_height <= height * .035):
                continue
            fill = area / max(component_width * component_height, 1)
            component_crop = patch[y:y + component_height, x:x + component_width]
            dark_ratio = float(np.mean(cv2.cvtColor(component_crop, cv2.COLOR_BGR2GRAY) < 95))
            if .30 <= fill <= .90 and .025 <= dark_ratio <= .38:
                best = max(best, fill + dark_ratio * .8)
        return False, best

    def _observe_dealer_anchors(self, frame, strict=False):
        scores = []
        for index in range(len(TABLE_LAYOUTS[self.layout])):
            present, score = self._dealer_present_in_slot(frame, index)
            scores.append((score if present else 0.0, index))
        scores.sort(reverse=True)
        threshold = .16 if strict else .12
        margin = .05 if strict else .035
        if not scores or scores[0][0] < threshold:
            return None
        if len(scores) > 1 and scores[0][0] - scores[1][0] < margin:
            return None
        return scores[0][1]

    def _slow_recognition_loop(self):
        while True:
            if not self.recognition_active.wait(.1):
                continue
            try:
                state = self._capture_slow_state()
                if state:
                    with self.state_lock:
                        current = self.cached_state or {}
                        protected = {key: current[key] for key in FAST_OWNED_FIELDS if key in current}
                        state = {key: value for key, value in state.items()
                                 if key in SLOW_STATE_FIELDS or key == "seats"}
                        slow_seats = state.pop("seats", None)
                        merged_seats = list(current.get("seats") or [])
                        by_index = {seat.get("index"): dict(seat) for seat in merged_seats}
                        for slow_seat in slow_seats or ():
                            index = slow_seat.get("index")
                            if index is None:
                                continue
                            merged = by_index.get(index, {"index": index})
                            merged.update({key: slow_seat[key] for key in SLOW_SEAT_FIELDS
                                           if key in slow_seat})
                            by_index[index] = merged
                        if by_index:
                            state["seats"] = [by_index[index] for index in sorted(by_index)]
                        merged_state = {**current, **state, **protected}
                        basics_ready = (
                            isinstance(merged_state.get("tablePlay"), dict) and
                            bool(merged_state["tablePlay"].get("type")) and
                            bool(merged_state.get("tableNumber")) and
                            bool(merged_state.get("blindTextRaw")) and
                            all(isinstance(merged_state.get(field), (int, float))
                                for field in ("blindSmall", "blindBig", "blindAnte",
                                              "rakeRate", "rakeCap"))
                        )
                        self.initial_identity_pending = (
                            not basics_ready and time.time() < self.initial_identity_deadline)
                        self.cached_state = merged_state
            except Exception as error:
                self.fields.commit("slowChannel", str(error), 0, "slow", False)
            self.slow_refresh_event.wait(.25 if self.initial_identity_pending else 2.0)
            self.slow_refresh_event.clear()

    def _slow_action_pressure(self):
        if self.force_slow_snapshot:
            return False
        return bool(
            getattr(self.action_ocr_queue, "unfinished_tasks", 0) or
            getattr(self.avatar_ocr_queue, "unfinished_tasks", 0) or
            self.action_ocr_pending_seats or self.avatar_ocr_pending_seats
        )

    def _seat_identity_ocr_items(self, frame, index, kinds=("name", "chips")):
        height, width = frame.shape[:2]
        items = []
        for kind in kinds:
            box = self._seat_slot_box(index, kind, width, height)
            if box and kind == "name":
                x1, y1, x2, y2 = box
                margin_x = max(3, round((x2 - x1) * .05))
                margin_y = max(4, round((y2 - y1) * .12))
                box = (max(0, x1 - margin_x), y1,
                       min(width, x2 + margin_x), min(height, y2 + margin_y))
            if box and kind == "chips":
                x1, y1, x2, y2 = box
                y1 = y1 + round((y2 - y1) * .42)
                box = (x1, y1, x2, y2)
            if not box:
                continue
            x1, y1, x2, y2 = box
            crop = frame[max(0, y1):min(height, y2), max(0, x1):min(width, x2)]
            if crop.size == 0:
                continue
            if kind == "name":
                detected = self._ocr_items(crop)
                text = " ".join(item.get("text", "") for item in detected).strip()
                confidence = max((float(item.get("confidence") or 0) for item in detected), default=0.0)
            else:
                text, confidence = self._ocr_line(cv2.resize(
                    crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC))
            if kind == "chips" and text and confidence < .9:
                gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
                gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
                retry_text, retry_confidence = self._ocr_line(cv2.resize(
                    gray, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC))
                if (self._extract_number(retry_text) == self._extract_number(text) and
                        retry_confidence > confidence):
                    text, confidence = retry_text, retry_confidence
            if text:
                items.append({"kind": kind, "text": text, "confidence": confidence,
                              "cx": (x1 + x2) / 2, "cy": (y1 + y2) / 2})
        return items

    def _capture_slow_identity_state(self, frame, captured_at, frame_sequence, started,
                                     include_names=True):
        height, width = frame.shape[:2]
        seats = []
        with self.state_lock:
            cached_seats = {seat.get("index"): dict(seat)
                            for seat in (self.cached_state or {}).get("seats", [])}
        for index, _center in enumerate(TABLE_LAYOUTS[self.layout]):
            tracker = self.seat_trackers.setdefault(index, {
                "occupancy": "unknown", "pendingOccupancy": None, "occupancyFrames": 0,
                "name": "", "chips": None, "avatar": "", "avatarHash": "",
                "stableBet": 0.0, "pendingBet": None, "betFrames": 0,
                "active": False, "lastAction": "waiting", "lastEvidence": "none",
            })
            identity = self._seat_identity_ocr_items(
                frame, index, ("name", "chips") if include_names else ("chips",))
            name_items = [item for item in identity if item.get("kind") == "name"]
            chip_items = [item for item in identity if item.get("kind") == "chips"]
            name_text = " ".join(item.get("text", "") for item in name_items)
            observed_name = self._extract_name(name_text)
            name_confidence = max((float(item.get("confidence") or 0) for item in name_items), default=0.0)
            if (observed_name and name_confidence >= .72 and
                    self._valid_player_name(observed_name)):
                if observed_name == tracker.get("pendingName"):
                    tracker["pendingNameFrames"] = tracker.get("pendingNameFrames", 0) + 1
                else:
                    tracker["pendingName"] = observed_name
                    tracker["pendingNameFrames"] = 1
                if (tracker["pendingNameFrames"] >= 2 and
                        ("mvp" not in observed_name.casefold() or not tracker.get("name"))):
                    tracker["name"] = observed_name
            self._observe_confirmed_profile_name(index, observed_name, tracker)
            if self.profile_confirmed_names.get(index):
                tracker["name"] = self.profile_confirmed_names[index]
            observed_chip = next((self._extract_number(item.get("text", ""))
                                  for item in reversed(chip_items)
                                  if self._extract_number(item.get("text", "")) is not None), None)
            observed_chip_text = next((item.get("text", "") for item in reversed(chip_items)
                                       if self._extract_number(item.get("text", "")) is not None), "")
            chip_confidence = max((float(item.get("confidence") or 0) for item in chip_items
                                   if self._extract_number(item.get("text", "")) is not None), default=0.0)
            chip_confidence = self._chip_confidence_with_consensus(
                index, observed_chip, observed_chip_text, chip_confidence)
            if observed_chip is not None and chip_confidence >= .75:
                tracker["chips"] = observed_chip
                tracker["chipConfidence"] = chip_confidence
            current_identity_evidence = bool(
                observed_name and name_confidence >= .72 and
                self._valid_player_name(observed_name)
            ) or bool(observed_chip is not None and chip_confidence >= .75)
            if current_identity_evidence:
                self._set_seat_occupancy(index, "occupied", "slow_seat_state",
                                         captured_at, getattr(self, "recording_second", None))
            current = cached_seats.get(index, {"index": index})
            seat = dict(current)
            seat.update({
                "index": index,
                "name": tracker.get("name", ""),
                "chips": tracker.get("chips"),
                "chipConfidence": tracker.get("chipConfidence", current.get("chipConfidence", 0.0)),
                "avatar": tracker.get("avatar", current.get("avatar", "")),
                "avatarHash": tracker.get("avatarHash", current.get("avatarHash", "")),
                "occupancy": tracker.get("occupancy", current.get("occupancy", "unknown")),
                "empty": tracker.get("occupancy") == "empty",
                "observedAt": captured_at if captured_at is not None else started,
                "frameSequence": frame_sequence,
                "videoSecond": getattr(self, "recording_second", None),
                "identityConfidence": max(
                    float(current.get("identityConfidence") or 0),
                    max((float(item.get("confidence") or 0) for item in identity), default=0.0)),
            })
            tracker["observedAt"] = seat["observedAt"]
            tracker["frameSequence"] = frame_sequence
            tracker["videoSecond"] = seat["videoSecond"]
            seats.append(seat)
        return {
            "seats": seats,
            "seatStateFrameCapturedAt": captured_at,
            "seatStateFrameSequence": frame_sequence,
            "seatStateHandId": self.hand_state.get("id", 0),
            "seatStateStreet": self.hand_state.get("street", "waiting"),
            "slowUpdatedAt": time.time(),
        }

    def _flush_history_state(self, seats):
        hand_id = self.hand_state.get("id", 0)
        if hand_id <= 0:
            return
        with self.action_state_lock:
            events = list(self.pending_history_events)
            self.pending_history_events.clear()
        hand = {
            "id": hand_id,
            "street": self.hand_state.get("street", "preflop"),
            "newHand": hand_id != self.history_last_hand_id,
            "heroPosition": position_for(
                self._current_hand_position_seats(seats),
                3 if self.layout == "6max" else 4,
                self.hand_dealer_index,
                self._straddle_seat_for_position(
                    self._current_hand_position_seats(seats), self.hand_dealer_index)),
        }
        self._observe_hero_range(
            hand_id, list(self.card_published.get("heroCards", [])),
            hand["heroPosition"])
        self.history_store.observe(
            hand, seats, events, self.hand_state.get("pot"),
            list(self.card_published.get("boardCards", [])),
            list(self.card_published.get("heroCards", [])),
        )
        self.history_last_hand_id = hand_id

    @staticmethod
    def _fast_change_fingerprint(frame):
        height, width = frame.shape[:2]
        global_view = cv2.resize(frame, (48, 48), interpolation=cv2.INTER_AREA)
        button_region = frame[int(height * .64):int(height * .95), :]
        button_view = cv2.resize(button_region, (64, 24), interpolation=cv2.INTER_AREA)
        return hashlib.blake2s(
            global_view.tobytes() + button_view.tobytes(), digest_size=8
        ).digest()

    def _fast_recognition_loop(self):
        previous_fingerprint = None
        while True:
            if not self.recognition_active.wait(.1):
                continue
            started = time.time()
            try:
                with self.capture_lock:
                    frame = self.latest_table_frame.copy() if self.latest_table_frame is not None else None
                fingerprint = (None if frame is None else
                               self._fast_change_fingerprint(frame))
                action_result_ready = not self.action_ocr_results.empty()
                if fingerprint is not None and (fingerprint != previous_fingerprint or action_result_ready):
                    previous_fingerprint = fingerprint
                    state = self._capture_fast_state()
                    if state:
                        push_strategy_state = False
                        with self.state_lock:
                            current = self.cached_state or {}
                            seat_count = len(TABLE_LAYOUTS[self.layout])
                            state_seats = state.get("seats")
                            if not isinstance(state_seats, list) or len(state_seats) < seat_count:
                                fallback_seats = current.get("seats") or self.fast_seat_snapshot
                                if isinstance(fallback_seats, list) and len(fallback_seats) >= seat_count:
                                    state["seats"] = [dict(seat) for seat in fallback_seats]
                            protected = {key: current.get(key) for key in (
                                "heroCards", "boardCards", "cardUpdatedAt", "cardFrameCapturedAt",
                                "cardFrameSequence", "cardLatencyMs"
                            ) if key in current}
                            self.cached_state = {**current, **state, **protected}
                            push_strategy_state = bool(
                                state.get("visualHeroTurn") and
                                self._strategy_push_key(self.cached_state) !=
                                self.last_pushed_strategy_state_key)
                        if push_strategy_state:
                            self._push_strategy_state()
            except Exception as error:
                self.fields.commit("fastChannel", str(error), 0, "fast", False)
            time.sleep(max(0.005, .015 - (time.time() - started)))

    def _push_strategy_state(self):
        snapshot = self.capture_state(compact=True)
        sequence = int(snapshot.get("actionButtonSequence") or 0)
        key = self._strategy_push_key(snapshot)
        if not sequence or key == self.last_pushed_strategy_state_key:
            return False
        self.last_pushed_action_button_sequence = sequence
        self.last_pushed_strategy_state_key = key
        self._record_preflop_strategy_shadow(snapshot)

        def deliver():
            callback = self.state_push_callback
            if callback is not None:
                callback(snapshot)
                return
            if self.window is None:
                return
            payload = json.dumps(snapshot, ensure_ascii=False, default=str)
            self.window.evaluate_js(
                f"window.__applyPushedState && window.__applyPushedState({payload})")

        threading.Thread(target=deliver, daemon=True).start()
        return True

    def _record_preflop_strategy_shadow(self, state):
        if state.get("street") != "preflop":
            return None
        identity = (
            self.runtime_id, self.table_session, state.get("handId"),
            state.get("street"), int(state.get("actionButtonSequence") or 0),
        )
        if not identity[-1] or identity in self.preflop_strategy_shadow_seen:
            return None
        self.preflop_strategy_shadow_seen.add(identity)
        hero_index = 3 if self.layout == "6max" else 4
        result = evaluate_preflop_shadow(state, hero_index)
        record = {
            "schemaVersion": 1, "mode": "read_only_shadow",
            "runtimeId": self.runtime_id, "tableSession": self.table_session,
            "handId": state.get("handId"),
            "actionButtonSequence": state.get("actionButtonSequence"),
            "videoSecond": state.get("decisionDataFrameVideoSecond"),
            "recordedAt": time.time(), "result": result,
            "formalAdviceChanged": False,
        }
        self._append_bounded_audit(self.preflop_strategy_shadow_file, record)
        return record

    @staticmethod
    def _strategy_push_key(state):
        return (
            state.get("runtimeId"), state.get("tableSession"), state.get("handId"),
            state.get("street"), int(state.get("actionButtonSequence") or 0),
            bool(state.get("visualHeroTurn")), bool(state.get("actionable")),
            state.get("expectedActionSeat"), state.get("actionStateFrameSequence"),
            tuple((item.get("street"), item.get("seat"), item.get("action"),
                   round(float(item.get("confidence") or 0), 3),
                   bool(item.get("orderConflict")), item.get("strategyEligible", True))
                  for item in (state.get("actionLog") or ())[-12:]),
        )

    def _fast_occupancy_loop(self):
        while True:
            if not self.recognition_active.wait(.1):
                continue
            started = time.time()
            try:
                frame, _ = self._frame_copy()
                if frame is not None and not self._detect_special_scene(frame):
                    self._scan_fast_occupancy(frame)
            except Exception as error:
                self.fields.commit("occupancyChannel", str(error), 0, "fast", False)
            time.sleep(max(.02, .15 - (time.time() - started)))

    def _scan_fast_occupancy(self, frame):
        height, width = frame.shape[:2]
        hero_index = 4 if self.layout == "8max" else 3
        for index in range(len(TABLE_LAYOUTS[self.layout])):
            avatar_box = self._seat_slot_box(index, "avatar", width, height)
            if not avatar_box:
                continue
            x1, y1, x2, y2 = avatar_box
            avatar = frame[max(0, y1):min(height, y2), max(0, x1):min(width, x2)]
            if avatar.size == 0:
                continue
            signature = cv2.resize(cv2.cvtColor(avatar, cv2.COLOR_BGR2GRAY), (16, 16),
                                   interpolation=cv2.INTER_AREA)
            previous = self.fast_occupancy_signatures.get(index)
            self.fast_occupancy_signatures[index] = signature
            if previous is None:
                continue
            candidate = self.fast_occupancy_candidates.setdefault(
                index, {"frames": 0, "lastDelta": 0.0, "stableFrames": 0, "anchor": previous.copy(),
                        "lastOccupancy": self.seat_trackers.get(index, {}).get("occupancy")})
            current_occupancy = self.seat_trackers.get(index, {}).get("occupancy")
            if current_occupancy != candidate.get("lastOccupancy"):
                candidate.update(frames=0, stableFrames=0, anchor=signature.copy(),
                                 lastOccupancy=current_occupancy)
                continue
            adjacent_delta = float(np.mean(cv2.absdiff(signature, previous)))
            anchor = candidate.get("anchor")
            anchor_delta = float(np.mean(cv2.absdiff(signature, anchor))) if anchor is not None else adjacent_delta
            delta = max(adjacent_delta, anchor_delta)
            tracker = self.seat_trackers.get(index, {})
            if (tracker.get("occupancy") != "empty" and
                    tracker.get("pendingOccupancy") != "empty"):
                candidate.update(frames=0, stableFrames=0, anchor=signature.copy(),
                                 lastOccupancy=tracker.get("occupancy"))
                continue
            pending_confirmation = (tracker.get("pendingOccupancy") is not None and
                                    tracker.get("pendingOccupancy") != tracker.get("occupancy") and
                                    tracker.get("occupancyFrames", 0) == 1)
            if delta < 5.5 and not pending_confirmation:
                candidate["frames"] = 0
                candidate["stableFrames"] = candidate.get("stableFrames", 0) + 1
                if candidate["stableFrames"] >= 8:
                    candidate["anchor"] = signature.copy()
                    candidate["stableFrames"] = 0
                continue
            candidate["stableFrames"] = 0
            candidate["frames"] += 1 if not pending_confirmation else 2
            candidate["lastDelta"] = delta
            if candidate["frames"] < 2:
                continue
            if index == hero_index and self.hero_cards_present:
                self._set_seat_occupancy(index, "occupied", "hero_cards_fast")
                candidate["frames"] = 0
                continue
            job = {"index": index, "avatar": avatar.copy(), "investment": None,
                   "occupancyProbe": True, "occupancyBefore": tracker.get("occupancy", "unknown"),
                   "visualDelta": delta, "handId": self.hand_state.get("id", 0),
                   "street": self.hand_state.get("street", "waiting"),
                   "observedAt": (self.latest_frame_captured_at
                                  if self.latest_frame_captured_at is not None else time.time()),
                   "frameReceivedAt": self.frame_received_at.get(self.latest_frame_sequence),
                   "frameSequence": self.latest_frame_sequence,
                   "videoSecond": getattr(self, "recording_second", None),
                   "triggerSource": "occupancy_delta", "visualFoldCandidate": False}
            try:
                with self.avatar_ocr_pending_lock:
                    if index in self.avatar_ocr_pending_seats:
                        continue
                    self.avatar_ocr_pending_seats.add(index)
                self._enqueue_avatar_ocr(job)
                candidate["anchor"] = signature.copy()
                candidate["frames"] = 0
            except queue.Full:
                with self.avatar_ocr_pending_lock:
                    self.avatar_ocr_pending_seats.discard(index)

    def _set_seat_occupancy(self, index, candidate, evidence, observed_at=None, video_second=None):
        tracker = self.seat_trackers.setdefault(index, {
            "occupancy": "unknown", "pendingOccupancy": None, "occupancyFrames": 0,
            "name": "", "chips": None, "avatar": "", "avatarHash": "",
            "stableBet": 0.0, "pendingBet": None, "betFrames": 0,
            "active": False, "lastAction": "waiting", "lastEvidence": "none",
        })
        if candidate == tracker.get("pendingOccupancy"):
            tracker["occupancyFrames"] += 1
        else:
            tracker["pendingOccupancy"], tracker["occupancyFrames"] = candidate, 1
        required = 1 if evidence in ("hero_cards_fast", "slow_seat_state",
                                     "action_avatar_empty_ocr") else 2
        if tracker["occupancyFrames"] < required or candidate == tracker.get("occupancy"):
            return False
        previous = tracker.get("occupancy", "unknown")
        hand_id = self.hand_state.get("id")
        participants = getattr(self, "hand_participants", {}).get(hand_id)
        joining_active_hand = bool(
            candidate == "occupied" and self.hand_state.get("active") and
            ((participants is not None and index not in participants) or
             participants is None and previous == "empty")
        )
        tracker.update(occupancy=candidate, active=candidate == "occupied", lastEvidence=evidence,
                       handEligible=candidate == "occupied" and not joining_active_hand)
        if joining_active_hand:
            tracker["joinedDuringHandId"] = hand_id
        elif candidate == "occupied" and tracker.get("joinedDuringHandId") != hand_id:
            tracker.pop("joinedDuringHandId", None)
        if candidate == "empty":
            self.profile_confirmed_names.pop(index, None)
            self.history_store.session_identities.pop(index, None)
            tracker.update(name="", pendingName="", pendingNameFrames=0,
                           chips=None, chipConfidence=0.0, avatar="", avatarHash="")
        if not hasattr(self, "seat_occupancy_trace"):
            self.seat_occupancy_trace = deque(maxlen=500)
        self.seat_occupancy_trace.append({"seat": index + 1, "from": previous, "to": candidate,
                                          "videoSecond": video_second if video_second is not None else getattr(self, "recording_second", None),
                                          "observedAt": observed_at if observed_at is not None else getattr(self, "latest_frame_captured_at", None),
                                          "confirmedAt": time.time(), "evidence": evidence})
        return True

    def _rebase_forced_bets_after_state_change(self):
        if not getattr(self, "waiting_for_forced_bets", False):
            return False
        hand_id = self.hand_state.get("id")
        if hand_id is None:
            return False
        if any(item.get("handId") == hand_id and
               item.get("action") not in ("blind", "post_blind", "straddle")
               for item in self.action_log):
            return False
        inferred = [item for item in self.action_log
                     if item.get("handId") == hand_id and item.get("inferred") and
                     item.get("action") in ("blind", "post_blind", "straddle")]
        if not inferred or self.hand_dealer_index is None:
            return False
        eligible = {index for index, tracker in self.seat_trackers.items()
                    if tracker.get("occupancy") == "occupied" and
                    tracker.get("handEligible", True) and
                    tracker.get("visualState") not in ("away", "waiting", "empty")}
        small = self._next_eligible_seat(self.hand_dealer_index, eligible)
        big = self._next_eligible_seat(small, eligible) if small is not None else None
        first_actor = self._next_eligible_seat(big, eligible) if big is not None else None
        if small is None or big is None:
            return False
        current_roles = {item.get("seat") for item in inferred}
        desired_roles = {small + 1, big + 1}
        if current_roles == desired_roles and self.formal_expected_seat == first_actor:
            return False
        self.action_log[:] = [item for item in self.action_log if item not in inferred]
        for tracker in self.seat_trackers.values():
            tracker.update(stableBet=0.0, pendingBet=None, betFrames=0)
        self.hand_participants[hand_id] = set(eligible)
        self.hand_player_counts[hand_id] = len(eligible)
        self.formal_expected_seat = first_actor
        self._set_forced_bet_seats(small, big, first_actor)
        amounts = ((small, self.blind_amounts.get("small")),
                   (big, self.blind_amounts.get("big")))
        for seat_index, amount in amounts:
            if amount in (None, 0):
                continue
            tracker = self.seat_trackers.get(seat_index, {})
            event = {"time": time.time(), "videoSecond": self.hand_started_second,
                     "observedAt": self.hand_started_second, "handId": hand_id,
                     "street": "preflop", "sequence": 0, "seat": seat_index + 1,
                     "name": tracker.get("name", ""), "action": "blind",
                     "avatarHash": tracker.get("avatarHash", ""), "amount": float(amount),
                     "increase": float(amount), "chipsAfter": tracker.get("chips"),
                     "potAfter": None, "confidence": .82, "inferred": True,
                     "evidence": "dealer_boundary+away_seat_rebased"}
            self._append_action_event(event)
            tracker["stableBet"] = float(amount)
        self._append_configured_forced_straddle(
            "牌桌盲注规则+庄家位置确认松浪盲注",
            observed_at=self.hand_started_second)
        return True

    def _set_forced_bet_seats(self, small, big, first_actor=None):
        self.forced_bet_seats = {
            "handId": self.hand_state.get("id"),
            "small": small,
            "big": big,
            "straddle": ((first_actor if first_actor is not None else
                          self._next_tracker_seat(big) if big is not None else None)
                         if self._straddle_allowed_for_hand() else None),
        }

    def _current_forced_bet_seats(self):
        seats = getattr(self, "forced_bet_seats", {})
        if seats.get("handId") == self.hand_state.get("id"):
            return seats.get("small"), seats.get("big"), seats.get("straddle")
        if self.hand_dealer_index is None:
            return None, None, None
        small = self._next_tracker_seat(self.hand_dealer_index)
        big = self._next_tracker_seat(small) if small is not None else None
        straddle = (self._next_tracker_seat(big) if big is not None and
                    self._straddle_allowed_for_hand() else None)
        self._set_forced_bet_seats(small, big, straddle)
        return small, big, straddle

    @staticmethod
    def _next_eligible_seat(current, eligible):
        if current is None or not eligible:
            return None
        for offset in range(1, 9):
            candidate = (current + offset) % 8
            if candidate in eligible:
                return candidate
        return None

    def bridge_info(self):
        return {"version": APP_VERSION, "runtimeId": self.runtime_id, "ready": True}

    def record_decision_latency(self, sample):
        if not isinstance(sample, dict):
            return {"recorded": False}
        numeric = {key: float(value) for key, value in sample.items()
                   if isinstance(value, (int, float)) and not isinstance(value, bool)}
        for key in ("calculationSource", "precalculationKey", "clockUnit",
                    "decisionButtonKey", "street"):
            if isinstance(sample.get(key), str):
                numeric[key] = sample[key]
        numeric["appVersion"] = APP_VERSION
        numeric["runtimeId"] = self.runtime_id
        numeric["recordedAt"] = time.time()
        self.decision_latency_samples.append(numeric)
        self._append_bounded_audit(self.decision_latency_file, numeric)
        return {"recorded": True, "count": len(self.decision_latency_samples)}

    def publish_training_decision(self, sample):
        if not isinstance(sample, dict):
            return {"recorded": False}
        record = dict(sample)
        record["appVersion"] = APP_VERSION
        record["runtimeId"] = self.runtime_id
        record["updatedAt"] = time.time()
        with self.state_lock:
            self.training_decision_state = record
        return {"recorded": True}

    def record_decision_audit(self, sample):
        if not isinstance(sample, dict):
            return {"recorded": False}
        record = dict(sample)
        record["appVersion"] = APP_VERSION
        record["runtimeId"] = self.runtime_id
        record["recordedAt"] = time.time()
        if record.get("status") == "rejected":
            reason = str(record.get("reason") or "").strip()
            record["reason"] = reason or "正式建议被拒绝，但调用方未提供具体原因"
            record["rejectionReason"] = record["reason"]
            record.pop("reasons", None)
        record["severity"] = self._decision_audit_severity(record)
        record["diagnosticDetail"] = (
            "full" if record["severity"] != "info" else "summary")
        if isinstance(record.get("v2Range"), dict):
            record["treeSummary"] = self._decision_tree_summary(record["v2Range"])
            if record["diagnosticDetail"] == "summary":
                record["v2Range"] = self._compact_v2_audit(record["v2Range"])
        identity = self._decision_audit_identity(record)
        encoded = json.dumps(record, ensure_ascii=False) + "\n"
        encoded_bytes = len(encoded.encode("utf-8"))
        with self.decision_audit_lock:
            if identity and identity in self.decision_audit_seen:
                return {"recorded": False, "reason": "duplicate_decision_audit"}
            if (record.get("status") == "formal" and
                    record.get("phase") == "formal_displayed" and
                    record.get("decisionButtonKey")):
                key = (record.get("runtimeId"), record.get("tableSession"),
                       record.get("handId"), record.get("street"),
                       int(record.get("actionButtonSequence") or 0))
                self.pending_hero_decisions[key] = dict(record)
                while len(self.pending_hero_decisions) > 128:
                    self.pending_hero_decisions.pop(next(iter(self.pending_hero_decisions)))
                if record.get("street") == "preflop":
                    with self.state_lock:
                        self.hero_range_decision_snapshot = dict(record)
            self._rotate_log_if_needed(
                self.decision_audit_file, self.decision_audit_max_bytes,
                self.decision_audit_backup_count, encoded_bytes)
            with self.decision_audit_file.open("a", encoding="utf-8") as handle:
                handle.write(encoded)
            if identity:
                self.decision_audit_seen.add(identity)
                self.decision_audit_seen_order.append(identity)
                while len(self.decision_audit_seen_order) > 512:
                    self.decision_audit_seen.discard(
                        self.decision_audit_seen_order.popleft())
        return {"recorded": True}

    @staticmethod
    def _decision_audit_identity(record):
        decision_id = record.get("decisionButtonKey") or record.get("decisionId")
        if not decision_id:
            return None
        return (str(decision_id), record.get("status"), record.get("phase"),
                record.get("stage"), int(record.get("retryAttempt") or 0),
                bool(record.get("final")))

    @staticmethod
    def _decision_audit_severity(record):
        v2_range = record.get("v2Range")
        v2_errors = (v2_range.get("parallelErrors")
                     if isinstance(v2_range, dict) else None)
        if record.get("error") or record.get("status") == "error":
            return "error"
        if (record.get("status") == "rejected" or record.get("parallelErrors") or
                v2_errors):
            return "warning"
        return "info"

    @staticmethod
    def _compact_response_tree(tree):
        if not isinstance(tree, dict):
            return None
        paths = tree.get("paths")
        return {key: value for key, value in {
            "orderedSeats": tree.get("orderedSeats"),
            "probabilities": tree.get("probabilities"),
            "pathCount": (len(paths) if isinstance(paths, list) else tree.get("pathCount")),
            "prunedProbability": tree.get("prunedProbability"),
            "sampleTier": tree.get("sampleTier"),
            "sampleCount": tree.get("sampleCount"),
            "source": tree.get("source"),
            "uncalibrated": tree.get("uncalibrated"),
            "responseMargin": tree.get("responseMargin"),
            "summaryFallback": tree.get("summaryFallback"),
        }.items() if value is not None}

    @classmethod
    def _compact_v2_candidate(cls, candidate):
        if not isinstance(candidate, dict):
            return None
        compact = {key: candidate.get(key) for key in (
            "candidateIndex", "action", "kind", "amount", "ratio", "ev",
            "evLow", "evHigh", "eligible", "selectionEligible",
            "riskGateReason", "classification", "classificationEvidence",
            "solveTier", "reason", "auditReasons") if key in candidate}
        tree = cls._compact_response_tree(candidate.get("responseTree"))
        if tree:
            compact["responseTree"] = tree
        return compact

    @classmethod
    def _compact_v2_decision(cls, decision):
        if not isinstance(decision, dict):
            return None
        compact = {key: decision.get(key) for key in (
            "modelVersion", "shadowOnly", "solveTier", "complete",
            "selectionTolerance", "decisionContext", "rangeSource",
            "parallelParts", "assumptions", "uncertaintyMethod") if key in decision}
        compact["best"] = cls._compact_v2_candidate(decision.get("best"))
        compact["rawBest"] = cls._compact_v2_candidate(decision.get("rawBest"))
        compact["evaluated"] = [cls._compact_v2_candidate(item)
                                for item in decision.get("evaluated", [])
                                if isinstance(item, dict)]
        trees = decision.get("responseTrees")
        if isinstance(trees, dict):
            compact["responseTrees"] = {
                key: cls._compact_response_tree(value)
                for key, value in trees.items() if isinstance(value, dict)}
        return compact

    @classmethod
    def _compact_v2_audit(cls, audit):
        compact = {key: audit.get(key) for key in (
            "modelVersion", "decisionId", "generatedAt", "shadowOnly",
            "opponentRoles", "calculationMs", "stageMs", "parallelStageMs",
            "deferredMs", "parallelErrors", "formalProposal", "formalGate")
                   if key in audit}
        compact["players"] = [
            {key: player.get(key) for key in (
                "seat", "name", "platformHands", "allowedToChangeAction", "reason",
                "difference", "remainingCombos", "defaultTop", "profiledTop",
                "actionTier", "showTier") if key in player} |
            {"stepCount": len(player.get("steps", []))}
            for player in audit.get("players", []) if isinstance(player, dict)]
        compact["decision"] = cls._compact_v2_decision(audit.get("decision"))
        compact["nextStreetDecision"] = cls._compact_v2_decision(
            audit.get("nextStreetDecision"))
        return compact

    @classmethod
    def _decision_tree_summary(cls, audit):
        decisions = [audit.get("decision"), audit.get("nextStreetDecision")]
        candidates = [item for decision in decisions if isinstance(decision, dict)
                      for item in decision.get("evaluated", []) if isinstance(item, dict)]
        trees = [item.get("responseTree") for item in candidates
                 if isinstance(item.get("responseTree"), dict)]
        return {
            "playerCount": len(audit.get("players", [])),
            "candidateCount": len(candidates),
            "responseTreeCount": len(trees),
            "responsePathCount": sum(
                len(tree.get("paths", [])) if isinstance(tree.get("paths"), list)
                else int(tree.get("pathCount") or 0) for tree in trees),
            "parallelErrorCount": len(audit.get("parallelErrors", [])),
            "stages": [decision.get("solveTier") for decision in decisions
                       if isinstance(decision, dict) and decision.get("solveTier")],
        }

    def _load_shadow_strategy_comparisons(self):
        rows = deque(maxlen=500)
        try:
            with self.strategy_comparison_file.open("r", encoding="utf-8") as handle:
                for line in handle:
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(row, dict):
                        rows.append(row)
        except OSError:
            pass
        return rows

    def _shadow_strategy_summary(self):
        rows = [row for row in getattr(self, "shadow_strategy_comparisons", ())
                if row.get("comparable") is True]
        scores = [float(row["pairedAdvantage"])
                  for row in rows if isinstance(row.get("pairedAdvantage"), (int, float))]
        agreements = sum(
            (row.get("autoBest") or {}).get("kind") ==
            (row.get("baselineBest") or {}).get("kind") for row in rows)
        average = sum(scores) / len(scores) if scores else None
        favored = ("auto" if average is not None and average > .001 else
                   "baseline" if average is not None and average < -.001 else
                   "tie" if average is not None else "insufficient")
        return {"samples": len(rows), "scoredSamples": len(scores),
                "agreementRate": agreements / len(rows) if rows else None,
                "averagePairedAdvantage": average, "favored": favored,
                "method": "paired_same_decision_cross_evaluation",
                "actualProfitProof": False}

    @staticmethod
    def _strategy_action_family(action):
        value = str(action or "").casefold()
        if value in ("fold", "弃牌"):
            return "fold"
        if value in ("check", "让牌", "过牌"):
            return "check"
        if value in ("call", "跟注"):
            return "call"
        if value in ("bet", "raise", "reraise", "allin", "下注", "加注", "再次加注", "全下"):
            return "raise"
        return None

    def _record_hero_strategy_comparison(self, event):
        hero_index = 3 if self.layout == "6max" else 4
        if (event.get("seat") != hero_index + 1 or
                event.get("action") in ("blind", "post_blind", "straddle")):
            return None
        sequence = int(event.get("actionButtonSequence") or 0)
        candidates = [(key, value) for key, value in self.pending_hero_decisions.items()
                      if key[0] == self.runtime_id and key[1] == self.table_session and
                      key[2] == event.get("handId") and key[3] == event.get("street") and
                      (not sequence or key[4] == sequence)]
        if not candidates:
            return None
        key, decision = max(candidates, key=lambda item: item[1].get("recordedAt", 0))
        recommended = self._strategy_action_family(decision.get("primary"))
        actual = self._strategy_action_family(event.get("action"))
        if not recommended or not actual:
            return None
        sample = {
            "runtimeId": self.runtime_id, "tableSession": self.table_session,
            "handId": event.get("handId"), "street": event.get("street"),
            "actionButtonSequence": key[4], "decisionButtonKey": decision.get("decisionButtonKey"),
            "position": decision.get("heroPosition", "unknown"),
            "recommended": recommended, "recommendedText": decision.get("primary"),
            "recommendedAmount": decision.get("recommended"),
            "actual": actual, "actualText": event.get("action"),
            "actualAmount": event.get("amount"),
            "matched": recommended == actual, "recordedAt": time.time(),
        }
        samples = self.hero_profile.setdefault("strategyComparisons", [])
        samples.append(sample)
        del samples[:-2000]
        self.pending_hero_decisions.pop(key, None)
        self._save_hero_profile()
        return sample

    def _hero_strategy_leaks(self):
        samples = [item for item in self.hero_profile.get("strategyComparisons", [])
                   if item.get("recommended") and item.get("actual")]
        opportunities = Counter(item["recommended"] for item in samples)
        patterns = (
            ("loose_calls", "不该继续时跟注过多", "fold", "call"),
            ("loose_raises", "不该继续时主动加注过多", "fold", "raise"),
            ("tight_folds", "可继续时弃牌过多", ("call", "raise"), "fold"),
            ("missed_raises", "错过价值或半诈唬加注", "raise", ("check", "call")),
            ("extra_aggression", "建议被动行动时额外加注过多", ("check", "call"), "raise"),
        )
        issues = []
        for code, label, recommended, actual in patterns:
            recommended_set = {recommended} if isinstance(recommended, str) else set(recommended)
            actual_set = {actual} if isinstance(actual, str) else set(actual)
            relevant = [item for item in samples if item["recommended"] in recommended_set]
            deviated = [item for item in relevant if item["actual"] in actual_set]
            count, total = len(deviated), len(relevant)
            rate = count / total if total else 0.0
            positions = Counter(item.get("position", "unknown") for item in deviated)
            issues.append({"code": code, "label": label, "count": count,
                           "opportunities": total, "rate": rate,
                           "eligible": total >= 15,
                           "flagged": total >= 15 and count >= 3 and rate >= .25,
                           "topPosition": positions.most_common(1)[0][0] if positions else None})
        return {"sampleCount": len(samples), "minimumComparable": 15,
                "matchedCount": sum(item.get("matched") is True for item in samples),
                "opportunities": dict(opportunities), "issues": issues,
                "status": ("ready" if any(item["eligible"] for item in issues)
                           else "insufficient")}

    def _start_dock_tracker(self):
        def track():
            last_bbox = None
            while True:
                if self.capture_bbox_locked:
                    current_bbox = self._current_bbox()
                    windows = visible_windows()
                    projection_window = projection_window_for_region(windows, current_bbox)
                    if projection_window and (self.config.get("hwnd") != projection_window["hwnd"] or current_bbox != projection_window["bbox"]):
                        current_bbox = list(projection_window["bbox"])
                        self.config.update({
                            "bbox": current_bbox,
                            "hwnd": projection_window["hwnd"],
                            "relative": [0, 0, 1, 1],
                            "source": f"完整投屏窗口 {projection_window['title'] or '竖屏窗口'}",
                            "captureLocked": True,
                        })
                        CONFIG_FILE.write_text(json.dumps(self.config, ensure_ascii=False, indent=2), encoding="utf-8")
                    recording_window = recording_window_for_region(windows, current_bbox)
                    if recording_window:
                        recording_bbox = self._recording_content_bbox(recording_window)
                        if recording_bbox and current_bbox != recording_bbox:
                            current_bbox = recording_bbox
                            self._save_bbox(current_bbox, f"录像内容区域 {recording_window['title']}", recording_window["hwnd"])
                            self.config["captureLocked"] = True
                    bbox = tuple(current_bbox) if self._bbox_valid(current_bbox) else None
                    if bbox:
                        with self.capture_lock:
                            self.tracked_bbox = list(bbox)
                    if bbox and bbox != last_bbox:
                        self.overlay.update(self._overlay_bbox(), visible=True, color=self.border_color)
                        last_bbox = bbox
                    if bbox:
                        self._dock_windows(bbox)
                    time.sleep(.25)
                    continue
                screenshot, (left, top) = capture_desktop()
                detected = detect_table(screenshot) if screenshot is not None else None
                table_event = self.table_presence.update(detected is not None)
                if table_event == "left":
                    self._begin_table_identity_reacquisition()
                    self.table_status = "已离开牌桌，正在寻找新牌桌"
                    self._record_table_event("left")
                    with self.capture_lock:
                        self.latest_table_frame = None
                        self.latest_capture_bbox = None
                    with self.state_lock:
                        self.cached_state = None
                elif table_event == "switched":
                    self.table_status = "牌桌已重新出现，正在核对稳定桌号"
                    self._record_table_event("identity_check_started")
                    self.force_slow_snapshot = True
                    self.slow_refresh_event.set()
                elif table_event == "found":
                    self.table_session += 1
                    self.table_status = "已找到牌桌，正在建立整桌信息"
                    self._record_table_event("found")
                    self.initial_identity_pending = True
                    self.initial_identity_deadline = time.time() + 6.0
                    self.force_slow_snapshot = True
                    self.slow_refresh_event.set()
                if detected:
                    tracked_bbox = [detected[0] + left, detected[1] + top, detected[2] + left, detected[3] + top]
                    projection_window = projection_window_for_region(visible_windows(), tracked_bbox)
                    if projection_window:
                        tracked_bbox = list(projection_window["bbox"])
                        self.config["hwnd"] = projection_window["hwnd"]
                        self.config["relative"] = [0, 0, 1, 1]
                        self.config["source"] = f"完整投屏窗口 {projection_window['title'] or '竖屏窗口'}"
                    current_bbox = self.tracked_bbox
                    if current_bbox and table_event not in ("found", "switched"):
                        current_area = max(1, (current_bbox[2] - current_bbox[0]) *
                                           (current_bbox[3] - current_bbox[1]))
                        detected_area = max(1, (tracked_bbox[2] - tracked_bbox[0]) *
                                            (tracked_bbox[3] - tracked_bbox[1]))
                        if detected_area < current_area * .95:
                            detected = None
                    if detected is None:
                        time.sleep(1.0)
                        continue
                    crop_box = [tracked_bbox[0] - left, tracked_bbox[1] - top,
                                tracked_bbox[2] - left, tracked_bbox[3] - top]
                    table_frame = cv2.cvtColor(screenshot[crop_box[1]:crop_box[3], crop_box[0]:crop_box[2]], cv2.COLOR_RGB2BGR)
                    with self.capture_lock:
                        self.tracked_bbox = tracked_bbox
                        self.latest_capture_bbox = tracked_bbox
                        self.latest_table_frame = table_frame
                        self.latest_frame_captured_at = time.time()
                        self.latest_frame_sequence += 1
                        self.latest_frame_video_second = getattr(self, "recording_second", None)
                        self.latest_frame_context = self._new_capture_context(
                            self.latest_frame_captured_at, self.latest_frame_sequence,
                            self.latest_frame_video_second)
                    if self.table_identity_reacquiring:
                        self.force_slow_snapshot = True
                        self.slow_refresh_event.set()
                    self.border_color = border_color(screenshot, detected, BORDER_WIDTH)
                bbox = tuple(self.tracked_bbox) if self.tracked_bbox else None
                if bbox != last_bbox and bbox:
                    self.overlay.update(self._overlay_bbox(), visible=True, color=self.border_color)
                    last_bbox = bbox
                if bbox:
                    self._dock_windows(bbox)
                time.sleep(1.0)

        threading.Thread(target=track, daemon=True).start()

    def _dock_windows(self, bbox=None):
        if not self.windows_docked:
            return {"docked": False}
        x1, y1, x2, y2 = self._overlay_bbox()
        height = max(500, y2 - y1)
        screen_left = user32.GetSystemMetrics(76)
        screen_width = user32.GetSystemMetrics(78)
        screen_right = screen_left + screen_width
        left_space = x1 - screen_left
        right_space = screen_right - x2
        panel_width = max(420, min(520, left_space // 2, right_space))
        positions = {}
        for title, side in (("训练辅助面板", "support"),
                            ("Poker Study Console", "console"),
                            ("Capture Audit", "audit")):
            if side == "audit" and not self.audit_visible:
                continue
            hwnd = self._window_hwnd(title)
            if not hwnd:
                continue
            target_width = round(panel_width * .85) if side == "support" else panel_width
            target_x = (x1 - panel_width - target_width if side == "support" else
                        x1 - panel_width if side == "console" else x2)
            user32.SetWindowPos(hwnd, 0, target_x, y1, target_width, height, 0x0010 | 0x0004)
            self._apply_topmost(hwnd, self.windows_topmost)
            positions[side] = [target_x, y1, target_width, height]
        return {"docked": True, "positions": positions}

    def set_window_docking(self, docked):
        self.windows_docked = bool(docked)
        result = self._dock_windows() if self.windows_docked else {"docked": False}
        return {"docked": self.windows_docked,
                "positions": result.get("positions", {}),
                "status": "控制台与辅助面板已在牌桌左侧等宽吸附" if self.windows_docked else "已解除窗口吸附，可以自由拖动"}

    def set_windows_topmost(self, topmost):
        self.windows_topmost = bool(topmost)
        for title in ("Poker Study Console", "训练辅助面板", "Capture Audit"):
            hwnd = self._window_hwnd(title)
            if hwnd:
                self._apply_topmost(hwnd, self.windows_topmost)
        return {"topmost": self.windows_topmost,
                "status": "训练窗口已置顶" if self.windows_topmost else "训练窗口已取消置顶"}

    @staticmethod
    def _apply_topmost(hwnd, topmost):
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        style = style | WS_EX_TOPMOST if topmost else style & ~WS_EX_TOPMOST
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        user32.SetWindowPos(hwnd, HWND_TOPMOST if topmost else HWND_NOTOPMOST, 0, 0, 0, 0,
                            0x0010 | 0x0002 | 0x0001 | 0x0040)

    def toggle_audit_window(self):
        if self.audit_window is None:
            return {"visible": False, "status": "采集审核台尚未创建"}
        self.audit_visible = not self.audit_visible
        if self.audit_visible:
            self.audit_window.show()
            self._dock_windows()
        else:
            self.audit_window.hide()
        return {"visible": self.audit_visible, "status": "采集审核台已开启" if self.audit_visible else "采集审核台已关闭"}

    def hide_audit_window(self):
        if self.shutting_down:
            return {"visible": False}
        self.audit_visible = False
        if self.audit_window is not None:
            self.audit_window.hide()
        return {"visible": False}

    def on_audit_closing(self):
        if self.shutting_down:
            return None
        self.hide_audit_window()
        return False

    def on_training_support_closing(self):
        if self.shutting_down:
            return None
        return False

    def close_application(self):
        self.shutting_down = True
        if self.overlay is not None:
            self.overlay.close()
        if self.audit_window is not None:
            self.audit_window.destroy()
        if self.training_support_window is not None:
            self.training_support_window.destroy()
        if self.hero_profile_window is not None:
            self.hero_profile_window.destroy()
        if self.opponent_hands_window is not None:
            self.opponent_hands_window.destroy()

    @staticmethod
    def _window_hwnd(expected_title):
        matches = []
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        @callback_type
        def callback(hwnd, _):
            if not user32.IsWindowVisible(hwnd) or user32.GetWindowTextLengthW(hwnd) <= 0:
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            title = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, title, length + 1)
            if expected_title not in title.value:
                return True
            rect = ctypes.wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            if rect.right - rect.left >= 400 and rect.bottom - rect.top >= 500:
                matches.append(((rect.right - rect.left) * (rect.bottom - rect.top), hwnd))
            return True

        user32.EnumWindows(callback, 0)
        return max(matches)[1] if matches else None

    def audit_snapshot(self):
        state = self.capture_state()
        # Keep the high-frequency audit response structural.  JPEG/base64
        # crops are available through audit_crops and are not sent every poll.
        crops = {}
        rows = []
        for name, item in state.get("fieldStatus", {}).items():
            confidence = float(item.get("confidence", 0))
            valid = not item.get("stale", False)
            rows.append({"field": name, "value": item.get("value"), "confidence": confidence,
                         "ageMs": item.get("ageMs"), "source": item.get("source", ""),
                         "observedAt": item.get("observedAt"), "confirmedAt": item.get("confirmedAt"),
                         "latencyMs": item.get("latencyMs"),
                         "crop": crops.get(name), "confirmed": valid, "ruleValid": valid and confidence >= .65,
                         "solverAllowed": valid and confidence >= .9})
        seats = [{key: seat.get(key) for key in ("index", "name", "chips", "action", "streetBet", "empty", "occupancy")}
                 for seat in state.get("seats", [])]
        actions = [{key: action.get(key) for key in ("handId", "street", "sequence", "seat", "name", "action", "amount", "orderConflict")}
                   for action in state.get("actionLog", [])[-30:]]
        decision_inputs = self._decision_inputs(state, crops)
        table_state = {key: state.get(key) for key in (
            "tablePlay", "tableNumber", "tableIdentityOcr", "blindTextRaw", "blindSmall", "blindBig", "blindStraddle", "blindAnte",
            "rakeRate", "rakeCap", "rakePlayers", "rakeSource", "dealerIndex", "dealerSeat", "dealerReliable", "pot", "activePlayerCount")}
        snapshot = {"version": APP_VERSION, "runtimeId": self.runtime_id,
                "status": state.get("status", ""), "rows": rows,
                "recognitionRunning": state.get("recognitionRunning", False),
                "decisionInputs": decision_inputs,
                "decisionBlockers": decision_inputs.get("blockers", []),
                "actionSnapshots": list(self.action_audit_snapshots),
                "seats": seats, "actions": actions, "frameSequence": state.get("frameSequence"),
                "handId": state.get("handId"), "street": state.get("street"),
                "frameBuffer": self.frame_buffer_status(),
                "pipelineEvents": list(self.pipeline_timestamps)[-50:],
                "dealerMonitor": {"currentSeat": None if self.dealer_monitor_current is None else self.dealer_monitor_current + 1,
                                  "events": list(self.dealer_monitor_events)[-20:]},
                "actionOcrQueue": {"pending": self.action_ocr_queue.qsize(),
                                   "completed": self.action_ocr_results.qsize(),
                                   "dropped": self.action_ocr_dropped},
                "decisionLatencySamples": list(self.decision_latency_samples)[-30:],
                "tableState": table_state,
                "peek": dict(state.get("peek") or self.peek_state),
                "profileStatisticsCapture": dict(self.profile_statistics_capture),
                "confirmedProfileSeats": self._confirmed_profile_seats(),
                "opponentProfiles": state.get("opponentProfiles", {}),
                "actionTimeline": self.action_timeline.snapshot(),
                "auditCropSequence": self.audit_crop_sequence,
                "auditCropsIncluded": False}
        self._record_audit_snapshot(snapshot)
        return snapshot

    def audit_crops(self):
        """Return the latest small audit crops on explicit request only."""
        return {"sequence": self.audit_crop_sequence, "crops": self._audit_crops()}

    def _record_audit_snapshot(self, snapshot):
        def without_images(value):
            if isinstance(value, dict):
                return {key: without_images(item) for key, item in value.items()
                        if key not in {"crop", "screenshot", "image", "avatar"}}
            if isinstance(value, list):
                return [without_images(item) for item in value]
            return value

        compact = {
            "recordedAt": time.time(), "version": APP_VERSION,
            "runtimeId": self.runtime_id,
            "handId": snapshot.get("handId"), "street": snapshot.get("street"),
            "tableState": snapshot.get("tableState"),
            "decisionInputs": without_images(snapshot.get("decisionInputs")),
            "seats": snapshot.get("seats"), "actions": snapshot.get("actions"),
            "actionTimeline": without_images(snapshot.get("actionTimeline")),
            "profileStatisticsCapture": snapshot.get("profileStatisticsCapture"),
        }
        signature = json.dumps({key: value for key, value in compact.items() if key != "recordedAt"},
                               ensure_ascii=False, sort_keys=True, default=str)
        if signature == getattr(self, "last_audit_snapshot_signature", None):
            return
        now = compact["recordedAt"]
        if (now - getattr(self, "last_audit_snapshot_at", 0.0) < self.audit_log_min_interval and
                snapshot.get("handId") == getattr(self, "last_audit_snapshot_hand_id", None)):
            return
        self.last_audit_snapshot_signature = signature
        self.last_audit_snapshot_at = now
        self.last_audit_snapshot_hand_id = snapshot.get("handId")
        self._rotate_log_if_needed(
            self.audit_file, self.audit_log_max_bytes,
            self.audit_log_backup_count)
        with self.audit_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(compact, ensure_ascii=False, default=str) + "\n")

    @staticmethod
    def _rotate_log_if_needed(path, maximum_bytes, backup_count=None,
                              incoming_bytes=0):
        try:
            if path.stat().st_size + max(0, int(incoming_bytes)) <= maximum_bytes:
                return
            stamp = time.strftime("%Y%m%d-%H%M%S")
            archive = path.with_name(f"{path.name}.{stamp}")
            suffix = 1
            while archive.exists():
                archive = path.with_name(f"{path.name}.{stamp}.{suffix}")
                suffix += 1
            path.replace(archive)
            if backup_count is not None:
                archives = sorted(
                    path.parent.glob(f"{path.name}.*"),
                    key=lambda item: item.stat().st_mtime, reverse=True)
                for expired in archives[max(0, int(backup_count)):]:
                    expired.unlink()
        except OSError:
            pass

    def _append_bounded_audit(self, path, record):
        encoded = json.dumps(record, ensure_ascii=False, default=str) + "\n"
        self._rotate_log_if_needed(
            path, self.audit_log_max_bytes, self.audit_log_backup_count,
            len(encoded.encode("utf-8")))
        with path.open("a", encoding="utf-8") as handle:
            handle.write(encoded)

    def action_audit_state(self):
        snapshots = self.action_audit_snapshots
        latest = snapshots[-1] if snapshots else None
        return {"count": len(snapshots), "latest": latest, "deliveredAt": time.time()}

    def pipeline_snapshot(self):
        with self.state_lock:
            state = dict(self.cached_state or {})
        state["fieldStatus"] = self.fields.snapshot()
        state["tableSession"] = self.table_session
        state["runtimeId"] = self.runtime_id
        with self.capture_lock:
            state["frameCapturedAt"] = self.latest_frame_captured_at
            state["frameSequence"] = self.latest_frame_sequence
            state["captureBbox"] = list(self.latest_capture_bbox or ())
        return build_pipeline_snapshot(state)

    def _flush_action_audits(self, state):
        if not self.pending_action_audits:
            return
        inputs = self._decision_inputs(state, self._audit_crops())
        while self.pending_action_audits:
            event = self.pending_action_audits.pop(0)
            self.action_audit_snapshots.append({"event": dict(event), "capturedAt": time.time(),
                                                "inputs": inputs["inputs"], "blockers": inputs["blockers"],
                                                "ready": inputs["ready"]})
        del self.action_audit_snapshots[:-100]

    def _publish_action_audit(self, event):
        if not hasattr(self, "state_lock"):
            return
        with self.state_lock:
            state = dict(self.cached_state or {})
        state.update({"actionLog": list(self.action_log), "fieldStatus": self.fields.snapshot(),
                      "handId": event.get("handId"), "street": event.get("street")})
        inputs = self._decision_inputs(state, {})
        self.action_audit_snapshots.append({"event": dict(event), "capturedAt": time.time(),
                                            "confirmedAt": event.get("time", time.time()),
                                            "inputs": inputs["inputs"], "blockers": inputs["blockers"],
                                            "ready": inputs["ready"]})
        del self.action_audit_snapshots[:-100]

    def _publish_confirmed_action_state(self, event):
        self._action_event_ledger().sync_projection(
            self.action_log, "confirmed_action_projection")
        if not hasattr(self, "state_lock"):
            return
        hero_index = 4 if self.layout == "8max" else 3
        published_at = time.time()
        with self.state_lock:
            state = dict(self.cached_state or {})
            seats = [dict(seat) for seat in state.get("seats") or []]
            if event.get("action") not in ("blind", "post_blind", "straddle"):
                actor = (event.get("seat") or 0) - 1
                if 0 <= actor < len(seats):
                    seats[actor]["action"] = event.get("action")
                    if event.get("amount") is not None:
                        seats[actor]["streetBet"] = event.get("amount")
            action_chain = self._action_chain_snapshot(
                event.get("handId"), event.get("street"))
            missing = next((item.get("missingSeats") or []
                            for item in action_chain.get("conflicts") or []
                            if item.get("missingSeats")), [])
            expected_seat = missing[0] if missing else action_chain.get("nextActorSeat")
            expected_index = None if expected_seat is None else int(expected_seat) - 1
            chain_closed = bool(
                action_chain.get("reliable") and
                action_chain.get("nextActor") == hero_index)
            if state.get("visualHeroTurn") and seats:
                state["reactionEstimates"] = self._reaction_estimates_for_state(
                    seats, state.get("pot"), state.get("callAmount"),
                    state.get("visualButtons") or state.get("buttons"), hero_index,
                    min_raise_to=state.get("minRaiseTo"),
                    allin_call=bool(state.get("allinCall")),
                )
            state.update({
                "actionLog": list(self.action_log),
                "actionCandidates": self.action_candidates[-30:],
                "expectedActionSeat": expected_seat,
                "heroActsAfterExpected": (
                    expected_index is not None and
                    self._next_tracker_seat(expected_index) == hero_index
                ),
                "actionChain": action_chain,
                "unactedPlayers": self._unacted_count(seats),
                "actionable": bool(
                    state.get("reliable") and state.get("visualHeroTurn") and
                    chain_closed
                ),
                "actionStatePublishedAt": published_at,
                "actionStateFrameSequence": event.get("frameSequence"),
            })
            if seats:
                state["seats"] = seats
            self.cached_state = state
        event["statePublishedAt"] = published_at
        self._mark_pipeline(
            "action_published", handId=event.get("handId"), seat=event.get("seat"),
            action=event.get("action"), frameSequence=event.get("frameSequence"),
        )

    def _decision_inputs(self, state, crops):
        seats = state.get("seats") or []
        hero_index = 3 if state.get("layout") == "6max" else 4
        hero_seat = seats[hero_index] if len(seats) > hero_index else {}
        actions = state.get("actionLog") or []
        field_status = state.get("fieldStatus") or {}
        folded = {action.get("seat") for action in actions
                  if action.get("handId") == state.get("handId") and action.get("action") == "fold"}
        eligible_indexes = self._current_hand_eligible_indices()
        active = [seat for seat in seats
                  if seat.get("index") in eligible_indexes and
                  not seat.get("empty") and seat.get("action") != "fold" and
                  seat.get("index", -1) + 1 not in folded]
        def item(key, label, value, valid, reason, crop_key=None,
                 observed_at=None, confirmed_at=None):
            field = field_status.get(key, {})
            confidence = float(field.get("confidence", 0))
            evidence_valid = bool(field and not field.get("stale", False) and
                                  field.get("source") and
                                  confidence >= ACTION_STRATEGY_CONFIDENCE)
            if key in HAND_SCOPED_FIELDS:
                evidence_valid = bool(
                    evidence_valid and field.get("handId") == state.get("handId") and
                    field.get("street") == state.get("street")
                )
            trusted = bool(valid and (key not in CONFIDENCE_GATED_FIELDS or evidence_valid))
            status = "ok" if trusted else "missing" if value is None or value == [] else "review"
            if valid and not trusted:
                reason = "识别结果存在，但来源、置信度或时效未达到精算门槛"
            return {"field": key, "label": label, "value": value, "status": status,
                    "confidence": confidence, "reason": reason if status != "ok" else "已识别并通过当前规则检查",
                    "observedAt": observed_at if observed_at is not None else field.get("observedAt"),
                    "confirmedAt": confirmed_at if confirmed_at is not None else field.get("confirmedAt"),
                    "latencyMs": field.get("latencyMs"), "crop": crops.get(crop_key or key)}
        board = state.get("boardCards")
        street = state.get("street")
        expected_board = {"preflop": 0, "flop": 3, "turn": 4, "river": 5}.get(street)
        current_actions = [action for action in actions
                           if action.get("handId") == state.get("handId") and
                           action.get("street") == street]
        last_action_pot = next((action.get("potAfter") for action in reversed(current_actions)
                                if isinstance(action.get("potAfter"), (int, float))), None)
        pot_value = state.get("pot")
        pot_reconciled = (isinstance(pot_value, (int, float)) and pot_value > 0 and
                          (last_action_pot is None or
                           abs(float(pot_value) - float(last_action_pot)) <= max(1.0, float(pot_value) * .12)))
        action_quality_reliable = all(
            not action.get("orderConflict") and action.get("strategyEligible", True) and
            float(action.get("confidence") or 0) >= ACTION_STRATEGY_CONFIDENCE
            for action in current_actions)
        hero_turn = bool(state.get("visualHeroTurn"))
        button_frame = state.get("visualButtonFrameCapturedAt")
        data_frame = state.get("decisionDataFrameCapturedAt")
        chip_frame = state.get("decisionChipFrameCapturedAt")
        data_sequence = state.get("decisionDataFrameSequence")
        chip_sequence = state.get("decisionChipFrameSequence")
        frame_aligned = (hero_turn and isinstance(button_frame, (int, float)) and
                         isinstance(data_frame, (int, float)) and
                         abs(float(data_frame) - float(button_frame)) <= .02)
        visible_hero = state.get("visibleHeroCards") or []
        stable_hero = state.get("heroCards") or []
        visible_board = state.get("visibleBoardCards") or []
        stable_board = state.get("boardCards") or []
        cards_aligned = (hero_turn and len(visible_hero) == 2 and visible_hero == stable_hero and
                         visible_board == stable_board)
        chip_stacks = state.get("decisionChipStacks") or {}
        required_chip_indexes = [seat.get("index") for seat in active]
        chips_present = bool(required_chip_indexes) and all(
            isinstance((chip_stacks.get(str(index)) or {}).get("value"), (int, float))
            for index in required_chip_indexes)
        chip_snapshot_aligned = (
            hero_turn and isinstance(chip_frame, (int, float)) and
            isinstance(button_frame, (int, float)) and abs(float(chip_frame) - float(button_frame)) <= .02 and
            chip_sequence == data_sequence and state.get("decisionChipHandId") == state.get("handId") and
            state.get("decisionChipStreet") == street and chips_present)
        chip_confident = chip_snapshot_aligned and all(
            float((chip_stacks.get(str(index)) or {}).get("confidence") or 0) >= ACTION_STRATEGY_CONFIDENCE
            for index in required_chip_indexes)
        chain_closed = (hero_turn and state.get("expectedActionSeat") == hero_index + 1 and
                        not state.get("heroActsAfterExpected"))
        inputs = [
            item("tablePlay", "牌桌玩法", state.get("tablePlay"),
                 isinstance(state.get("tablePlay"), dict) and bool(state.get("tablePlay", {}).get("type")),
                 "玩法文字尚未可靠解析"),
            item("tableNumber", "牌桌号", state.get("tableNumber"),
                 bool(state.get("tableNumber")), "桌号尚未连续两次一致"),
            item("blindTextRaw", "盲注原文", state.get("blindTextRaw"),
                 bool(state.get("blindTextRaw")) and all(isinstance(state.get(key), (int, float))
                 for key in ("blindSmall", "blindBig", "blindAnte")),
                 "盲注原文、小盲、大盲或前注不完整"),
            item("blindSmall", "小盲", state.get("blindSmall"),
                 isinstance(state.get("blindSmall"), (int, float)) and state.get("blindSmall") > 0,
                 "小盲尚未可靠解析"),
            item("blindBig", "大盲", state.get("blindBig"),
                 isinstance(state.get("blindBig"), (int, float)) and
                 state.get("blindBig") > float(state.get("blindSmall") or 0),
                 "大盲尚未可靠解析或不大于小盲"),
            item("blindStraddle", "Straddle", state.get("blindStraddle"),
                 state.get("blindStraddle") is None or isinstance(state.get("blindStraddle"), (int, float)),
                 "Straddle尚未可靠解析"),
            item("blindAnte", "前注", state.get("blindAnte"),
                 isinstance(state.get("blindAnte"), (int, float)) and state.get("blindAnte") >= 0,
                 "前注尚未可靠解析"),
            item("rakeRate", "抽成率", state.get("rakeRate"),
                 isinstance(state.get("rakeRate"), (int, float)), "当前盲注未匹配抽成表"),
            item("rakeCap", "抽成上限", state.get("rakeCap"),
                 isinstance(state.get("rakeCap"), (int, float)), "当前盲注与人数未匹配抽成上限"),
            item("rakePlayers", "抽成按在局人数", state.get("rakePlayers"),
                 isinstance(state.get("rakePlayers"), int) and 2 <= state.get("rakePlayers") <= 8,
                 "用于匹配抽成上限的在局人数尚未确认"),
            item("visualHeroTurn", "是否轮到本人", state.get("visualHeroTurn"), bool(state.get("visualHeroTurn")), "未识别到本人正式动作按钮", "buttons"),
            item("actionButtonSequence", "本次正式按钮序号", state.get("actionButtonSequence"),
                 hero_turn and isinstance(state.get("actionButtonSequence"), int) and
                 state.get("actionButtonSequence") > 0,
                 "正式按钮尚未生成本次唯一序号", "buttons", button_frame,
                 state.get("actionButtonDetectedAt")),
            item("decisionFrameAlignment", "按钮与决策数据同帧",
                 {"buttonFrame": button_frame, "dataFrame": data_frame,
                  "frameSequence": data_sequence}, frame_aligned,
                 "正式按钮与牌面、底池等决策数据不是同一采集帧", "buttons",
                 button_frame, data_frame),
            item("heroCards", "本人的两张牌", state.get("heroCards"), len(state.get("heroCards") or []) == 2, "手牌缺失或不是两张", "heroCards"),
            item("boardCards", "公共牌", board if board is not None else [], expected_board is not None and len(board or []) == expected_board, "公共牌数量与当前阶段不一致", "boardCards"),
            item("visibleCardsAligned", "按钮时刻牌面一致",
                 {"hero": visible_hero, "board": visible_board}, cards_aligned,
                 "按钮时刻画面牌面与本手稳定牌面不一致", "heroCards", data_frame),
            item("street", "当前阶段", street, street in ("preflop", "flop", "turn", "river"), "当前阶段缺失或冲突"),
        item("heroPosition", "本人位置", state.get("heroPosition"), state.get("heroPosition") not in (None, "unknown"), "庄家、空座或位置尚未可靠"),
            item("dealerSeat", "庄家座位", (state.get("dealerSeat") if state.get("dealerSeat") is not None else
                                              state.get("dealerIndex") + 1 if isinstance(state.get("dealerIndex"), int) else None),
                 (state.get("dealerSeat") is not None or isinstance(state.get("dealerIndex"), int)) and bool(state.get("dealerReliable")),
                 "庄家D尚未连续确认，或与本手庄家记录冲突"),
            item("activePlayerCount", "当前在局人数", state.get("activePlayerCount"),
                 isinstance(state.get("activePlayerCount"), int) and state.get("activePlayerCount") >= 2,
                 "当前在局人数少于2人或尚未确认"),
            item("pot", "当前底池", pot_value, pot_reconciled,
                 "底池金额缺失，或与当前阶段最后动作金额无法对账", "pot"),
            item("callAmount", "需要补齐量", state.get("callAmount"), isinstance(state.get("callAmount"), (int, float)), "跟注量未从正式按钮确认", "callAmount"),
            item("buttons", "可用动作及金额", state.get("visualButtons") or state.get("buttons"), bool(state.get("visualButtons") or state.get("buttons")), "正式动作按钮缺失", "buttons"),
            item("heroStack", "本人剩余筹码", hero_seat.get("chips"), isinstance(hero_seat.get("chips"), (int, float)), "本人筹码缺失"),
            item("opponentStacks", "相关对手筹码", [{"seat": s.get("index", 0)+1, "name": s.get("name"), "chips": s.get("chips")} for s in active if s is not hero_seat], bool(active) and all(isinstance(s.get("chips"), (int, float)) for s in active), "一个或多个活跃对手筹码缺失"),
            item("decisionChipSnapshot", "按钮时刻相关玩家筹码",
                 [{"seat": index + 1,
                   "name": next((seat.get("name") for seat in active
                                 if seat.get("index") == index), ""),
                   "chips": (chip_stacks.get(str(index)) or {}).get("value"),
                   "confidence": (chip_stacks.get(str(index)) or {}).get("confidence")}
                  for index in required_chip_indexes], chip_snapshot_aligned,
                 "筹码快照与按钮不同帧、手号或阶段不一致，或相关玩家筹码缺失",
                 observed_at=chip_frame),
            item("decisionChipConfidence", "按钮时刻筹码可信度",
                 [{"seat": index + 1,
                   "confidence": (chip_stacks.get(str(index)) or {}).get("confidence")}
                  for index in required_chip_indexes], chip_confident,
                 "一个或多个相关玩家筹码可信度低于82%", observed_at=chip_frame),
            item("actionLog", "已记录动作质量", current_actions, action_quality_reliable,
                 "当前阶段存在低于82%的动作或规则顺序冲突"),
            item("actionChainClosed", "本人行动前动作链闭合",
                 {"expectedSeat": state.get("expectedActionSeat"),
                  "heroSeat": hero_index + 1}, chain_closed,
                 "规则账本的当前行动人不是本人，前序动作可能缺失"),
            item("stateReliable", "后端精算基础状态", state.get("reliable"),
                 state.get("reliable") is True,
                 "牌面、阶段、底池、庄位、位置或动作规则尚未全部可靠"),
            item("preflopFullRaiseCount", "翻牌前完整加注次数",
                 state.get("preflopFullRaiseCount"),
                 street != "preflop" or isinstance(state.get("preflopFullRaiseCount"), int),
                 "翻牌前完整加注次数尚未确认"),
            item("unactedPlayers", "后面未行动人数", state.get("unactedPlayers"), isinstance(state.get("unactedPlayers"), int), "未行动人数尚未确认"),
        ]
        hard_gate_fields = {
            "visualHeroTurn", "actionButtonSequence", "decisionFrameAlignment",
            "heroCards", "boardCards", "visibleCardsAligned", "street", "heroPosition",
            "dealerIndex", "activePlayerCount", "pot", "callAmount", "buttons", "decisionChipSnapshot",
            "decisionChipConfidence", "actionLog", "actionChainClosed", "stateReliable",
        }
        if street == "preflop":
            hard_gate_fields.update({"tablePlay", "blindTextRaw", "preflopFullRaiseCount"})
        for entry in inputs:
            entry["blocking"] = entry["field"] in hard_gate_fields
        blockers = [entry["label"] + "：" + entry["reason"] for entry in inputs
                    if entry["blocking"] and entry["status"] != "ok"]
        return {"capturedAt": time.time(), "handId": state.get("handId"), "street": street,
                "heroTurn": bool(state.get("visualHeroTurn")), "inputs": inputs, "blockers": blockers,
                "ready": not blockers}

    def _audit_crops(self):
        with self.capture_lock:
            frame = self.latest_table_frame.copy() if self.latest_table_frame is not None else None
            sequence = self.latest_frame_sequence
        if frame is None:
            return {}
        now = time.time()
        if sequence == self.audit_crop_sequence or now - self.audit_crop_at < 1.0:
            return self.audit_crop_cache
        height, width = frame.shape[:2]
        regions = {"heroCards": (.25, .72, .75, .97), "boardCards": (.18, .38, .82, .62),
                   "pot": (.34, .25, .66, .48), "callAmount": (.48, .72, 1, 1), "buttons": (.25, .62, 1, 1)}
        result = {}
        for field, ratios in regions.items():
            x1, y1, x2, y2 = ratios
            crop = frame[int(height*y1):int(height*y2), int(width*x1):int(width*x2)]
            if crop.size == 0:
                continue
            scale = min(1.0, 260 / max(crop.shape[1], 1))
            if scale < 1:
                crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            ok, encoded = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 65])
            if ok:
                result[field] = "data:image/jpeg;base64," + base64.b64encode(encoded).decode()
        self.audit_crop_cache = result
        self.audit_crop_sequence = sequence
        self.audit_crop_at = now
        return result

    def submit_audit_correction(self, payload):
        field = str((payload or {}).get("field", "")).strip()
        if not field:
            return {"saved": False, "error": "缺少字段名称"}
        state = self.capture_state()
        item = (state.get("fieldStatus") or {}).get(field, {})
        record = {"savedAt": time.time(), "version": APP_VERSION, "field": field,
                  "recognized": (payload or {}).get("recognized", item.get("value")), "correct": (payload or {}).get("correct"),
                  "note": str((payload or {}).get("note", ""))[:200],
                  "handId": state.get("handId"), "street": state.get("street")}
        self._append_bounded_audit(self.audit_review_file, record)
        return {"saved": True, "record": record}

    def audit_accuracy(self):
        counts = {}
        source = self.audit_review_file if self.audit_review_file.exists() else self.audit_file
        if source.exists():
            for line in source.read_text(encoding="utf-8").splitlines():
                try:
                    item = json.loads(line)
                except ValueError:
                    continue
                entry = counts.setdefault(item.get("field"), {"reviewed": 0, "correct": 0})
                entry["reviewed"] += 1
                entry["correct"] += int(item.get("recognized") == item.get("correct"))
        for entry in counts.values():
            entry["accuracy"] = round(entry["correct"] / entry["reviewed"] * 100, 1)
        return counts

    def set_overlay(self, enabled):
        self.overlay_enabled = True
        if self.overlay is not None:
            self.overlay.update(self._overlay_bbox(), visible=True)
        return {"enabled": self.overlay_enabled}

    def lock_capture_box(self):
        with self.capture_lock:
            if not self.tracked_bbox:
                saved_bbox = self.config.get("bbox")
                if isinstance(saved_bbox, list) and len(saved_bbox) == 4:
                    self.tracked_bbox = list(map(int, saved_bbox))
            if not self.tracked_bbox:
                return {"locked": False, "status": "尚未找到牌桌，不能锁定"}
            bbox = list(map(int, self.tracked_bbox))
            windows = visible_windows()
            projection_window = projection_window_for_region(windows, bbox)
            if projection_window:
                bbox = list(projection_window["bbox"])
                self.tracked_bbox = bbox
                self.config["hwnd"] = projection_window["hwnd"]
                self.config["relative"] = [0, 0, 1, 1]
                self.config["source"] = f"完整投屏窗口 {projection_window['title'] or '竖屏窗口'}"
            recording_window = recording_window_for_region(windows, bbox)
            if recording_window:
                recording_bbox = self._recording_content_bbox(recording_window)
                if recording_bbox:
                    bbox = recording_bbox
                    self.tracked_bbox = bbox
                    self._save_bbox(bbox, f"录像内容区域 {recording_window['title']}", recording_window["hwnd"])
            self.capture_bbox_locked = True
            self.config["bbox"] = bbox
            self.config["captureLocked"] = True
            CONFIG_FILE.write_text(json.dumps(self.config, ensure_ascii=False, indent=2), encoding="utf-8")
        self.table_status = "采集框已锁定，只采集固定区域"
        return {"locked": True, "bbox": bbox, "status": self.table_status}

    def unlock_capture_box(self):
        self.capture_bbox_locked = False
        self.config["captureLocked"] = False
        CONFIG_FILE.write_text(json.dumps(self.config, ensure_ascii=False, indent=2), encoding="utf-8")
        self.table_status = "采集框已解锁，恢复自动吸附"
        return {"locked": False, "status": self.table_status}

    def solver_status(self):
        return self.strategy_store.solver_status()

    def match_strategy(self, state):
        return self.strategy_store.match_formal(state)

    def _removed_calibrate(self, mode="auto"):
        self.calibration_confirmed = False
        self.tracked_bbox = None
        result = self._auto_calibrate() if mode == "auto" else None
        if result is None and mode != "auto":
            bbox = self._select_region_threaded()
            if not bbox:
                self.overlay.update(self._overlay_bbox(), visible=True)
                return {"status": "已取消框选，保留原区域"}
            result = self._save_bbox(bbox, "手动定位")
        if result:
            self.overlay.update(self._overlay_bbox(), visible=True)
            preview = self.preview_calibration()
            result.update(preview)
        if result:
            return result
        if self._bbox_valid(self._visible_bbox()):
            player_count = len(TABLE_LAYOUTS[self.layout])
            return {"status": "本次未检测到绿色牌桌，已保留当前有效定位；可手动调整或直接确认", "layout": self.layout, "playerCount": player_count, "bbox": self._visible_bbox()}
        return {"status": "自动定位失败，请点击手动定位"}

    def _removed_preview_calibration(self):
        bbox = tuple(self._visible_bbox())
        screenshot = ImageGrab.grab(bbox=bbox)
        frame = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
        self.layout = self._detect_layout(frame)
        self.config["layout"] = self.layout
        CONFIG_FILE.write_text(json.dumps(self.config, ensure_ascii=False, indent=2), encoding="utf-8")
        player_count = len(TABLE_LAYOUTS[self.layout])
        return {"layout": self.layout, "playerCount": player_count, "seats": [], "status": f"已框住投屏，初步判断为 {player_count} 人桌；确认边框后再启动识别"}

    def _removed_confirm_calibration(self):
        self.calibration_confirmed = True
        self.tracked_bbox = list(self._visible_bbox())
        self.overlay.update(self._overlay_bbox(), visible=True)
        self._dock_console()
        return {"status": f"已确认 {len(TABLE_LAYOUTS[self.layout])} 人桌，可启动识别", "layout": self.layout}

    def _select_region_threaded(self):
        result = {"bbox": None, "error": None}
        def run():
            try:
                result["bbox"] = self._adjust_region(self._visible_bbox())
            except Exception as error:
                result["error"] = str(error)
        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        worker.join()
        if result["error"]:
            raise RuntimeError(f"框选失败：{result['error']}")
        return result["bbox"]

    def _adjust_region(self, initial_bbox):
        if getattr(sys, "frozen", False):
            command = [sys.executable, "--manual-calibrate", json.dumps(initial_bbox)]
        else:
            command = [sys.executable, str(Path(__file__).with_name("manual_calibrator.py")), json.dumps(initial_bbox)]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=300)
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "手动定位窗口启动失败")
        lines = [line for line in completed.stdout.splitlines() if line.strip()]
        return json.loads(lines[-1]) if lines else None

    def capture_state(self, compact=False):
        with self.state_lock:
            source = self.cached_state or {}
            if compact:
                allowed = {
                    "status", "seats", "heroCards", "visibleHeroCards", "boardCards", "visibleBoardCards",
                    "visualHeroTurn", "visualButtons", "buttons", "heroTurn", "actionable", "reliable",
                    "recognitionReliable", "actionQualityReliable",
                    "handId", "street", "pot", "callAmount", "minRaiseTo", "heroPosition", "dealerIndex", "dealerSeat", "dealerReliable",
                    "layout", "runtimeId", "tableSession", "opponentProfiles", "actionLog", "preflopFullRaiseCount",
                    "handParticipants", "activeHandParticipants",
                    "rakeRate", "rakeCap", "tablePlay", "tableNumber", "tableIdentityOcr", "blindTextRaw", "blindSmall", "blindBig", "blindStraddle", "blindAnte", "decisionDataFrameCapturedAt", "decisionDataFrameSequence",
                    "rakePlayers", "rakeSource",
                    "decisionDataFrameReceivedAt", "visualButtonFrameCapturedAt", "actionButtonDetectedAt",
                    "actionButtonFrameCapturedAt", "actionButtonFrameReceivedAt", "actionButtonSequence",
                    "actionButtonStatePublishedAt",
                    "heroPreselection", "actionButtonPreselection",
                    "actionButtonHandId", "actionButtonStreet", "actionButtonFrameSequence",
                    "decisionBindingReliable", "allinCall", "allinCallAmount",
                    "actionStatePublishedAt", "actionStateFrameSequence",
                    "decisionChipFrameCapturedAt", "decisionChipFrameSequence", "decisionChipStacks",
                    "decisionChipHandId", "decisionChipStreet", "seatStateFrameSequence",
                    "seatStateHandId", "seatStateStreet", "expectedActionSeat", "heroActsAfterExpected",
                    "actionChain", "actionEngineMode", "actionEngineStatus",
                    "activePlayerCount", "specialScene", "spectator", "peek", "reactionEstimates",
                    "exploitStrategy",
                    "fastStageMs", "fastTotalMs"
                    ,"trainingDecision"
                }
                snapshot = {key: source.get(key) for key in allowed if key in source}
            else:
                snapshot = dict(source)
        if not snapshot:
            return {"status": f"v{APP_VERSION} · {self.table_status}", "seats": [], "reliable": False,
                    "actionable": False, "spectator": True, "tableSession": self.table_session,
                    "runtimeId": self.runtime_id,
                    "actionEngineMode": self.action_engine_mode,
                    "actionEngineStatus": self.action_engine_status,
                    "actionEventCount": self._action_event_ledger().count(),
                    "tableEvents": self.table_events[-10:],
                    "captureBoxLocked": self.capture_bbox_locked, "windowsDocked": self.windows_docked,
                    "windowsTopmost": self.windows_topmost,
                    "heroProfileVisible": self.hero_profile_visible,
                    "opponentHandsVisible": self.opponent_hands_visible,
                    "heroProfileTopmost": self.hero_profile_topmost,
                    "opponentHandsTopmost": self.opponent_hands_topmost,
                    "strategyMode": self.strategy_mode,
                    "strategyComparisonSummary": self._shadow_strategy_summary(),
                    "profileStatisticsCapture": dict(self.profile_statistics_capture),
                    "trainingDecision": dict(self.training_decision_state),
                    "confirmedProfileSeats": self._confirmed_profile_seats(),
                    "recognitionRunning": self.recognition_active.is_set(),
                    "fieldStatus": self.fields.snapshot()}
        if not compact:
            snapshot["fieldStatus"] = self.fields.snapshot()
        snapshot["recognitionRunning"] = self.recognition_active.is_set()
        active_player_count = snapshot.get("activePlayerCount", 0)
        table_status = ("正在识别牌桌" if isinstance(active_player_count, int) and
                        active_player_count >= 2 else self.table_status)
        snapshot["status"] = f"v{APP_VERSION} · {table_status} · {active_player_count}人"
        snapshot["tableSession"] = self.table_session
        snapshot["runtimeId"] = self.runtime_id
        with self.state_lock:
            snapshot["trainingDecision"] = dict(self.training_decision_state)
        snapshot["actionEngineMode"] = self.action_engine_mode
        snapshot["actionEngineStatus"] = self.action_engine_status
        snapshot["actionEventCount"] = self._action_event_ledger().count()
        if not compact:
            snapshot["actionEventTail"] = self._action_event_ledger().snapshot()[-50:]
        hand_id = snapshot.get("handId")
        snapshot["handParticipants"] = sorted(
            index + 1 for index in self.hand_participants.get(hand_id, set()))
        snapshot["activeHandParticipants"] = sorted(
            index + 1 for index in self._current_hand_eligible_indices())
        snapshot["seats"] = [dict(item) for item in snapshot.get("seats") or ()]
        snapshot["actionLog"] = [dict(item) for item in snapshot.get("actionLog") or ()]
        expected_board_count = {
            "preflop": 0, "flop": 3, "turn": 4, "river": 5,
        }.get(snapshot.get("street"))
        if (expected_board_count is not None and
                len(snapshot.get("boardCards") or ()) != expected_board_count):
            snapshot.update(
                visualHeroTurn=False, heroTurn=False, actionable=False,
                visualButtons=[], buttons=[], decisionBindingReliable=False,
            )
        snapshot["exploitStrategy"] = self.exploit_strategy.assess(
            snapshot, 3 if self.layout == "6max" else 4)
        if snapshot.get("street") == "preflop":
            snapshot["scenarioBaseline"] = evaluate_preflop_shadow(
                snapshot, 3 if self.layout == "6max" else 4)
        if not compact:
            snapshot["tableEvents"] = self.table_events[-10:]
        snapshot["captureBoxLocked"] = self.capture_bbox_locked
        snapshot["windowsDocked"] = self.windows_docked
        snapshot["windowsTopmost"] = self.windows_topmost
        snapshot["heroProfileVisible"] = self.hero_profile_visible
        snapshot["opponentHandsVisible"] = self.opponent_hands_visible
        snapshot["heroProfileTopmost"] = self.hero_profile_topmost
        snapshot["opponentHandsTopmost"] = self.opponent_hands_topmost
        snapshot["strategyMode"] = self.strategy_mode
        snapshot["strategyComparisonSummary"] = self._shadow_strategy_summary()
        snapshot["profileStatisticsCapture"] = dict(self.profile_statistics_capture)
        snapshot["confirmedProfileSeats"] = self._confirmed_profile_seats()
        # Do not serialize full avatar images on every 10 ms UI poll. The
        # console only needs the stable fingerprint; audit crops remain
        # available through the dedicated audit snapshot.
        snapshot["seats"] = [
            {key: value for key, value in seat.items() if key != "avatar"}
            for seat in snapshot.get("seats", [])
        ]
        profiles = snapshot.get("opponentProfiles")
        if isinstance(profiles, dict):
            snapshot["opponentProfiles"] = {
                identity: {key: value for key, value in profile.items()
                           if key not in {"avatar", "avatarHistory", "avatarSamples", "identityHistory"}}
                for identity, profile in profiles.items()
            }
        if compact:
            # Keep only the current hand's tail for the strategy view.
            # Historical actions remain available from the audit endpoint.
            hand_id = snapshot.get("handId")
            log = snapshot.get("actionLog") or []
            action_fields = {
                "handId", "street", "sequence", "actionRound", "seat", "name",
                "action", "amount", "increase", "orderConflict", "strategyEligible",
                "confidence", "evidence", "chainStatus", "potBefore", "position",
                "effectiveStackBb", "playerCount", "betPotRatio", "boardAtAction",
                "facingAction",
            }
            snapshot["actionLog"] = [
                {key: item.get(key) for key in action_fields if key in item}
                for item in log if item.get("handId") == hand_id
            ][-32:]
            profile_fields = {
                "name", "hands", "preflopOpportunities", "vpipHands", "pfrHands",
                "postflopCalls", "postflopBets", "postflopRaises",
                "facingBetOpportunities", "foldsFacingBet", "platformStatistics",
                "revealedHands", "decisionSampleCount", "verifiedDecisionSampleCount",
            }
            profiles = snapshot.get("opponentProfiles")
            if isinstance(profiles, dict):
                compact_profiles = {}
                evidence_fields = {
                    "modelVersion", "nAction", "nShow", "revealedHands", "shadowOnly",
                }
                bucket_fields = {
                    "street", "facingAction", "position", "boardClass", "ratioBucket",
                    "stackBucketBb", "playerCountBucket", "sampleCount", "verifiedCount",
                    "actionCounts", "verifiedClasses", "matchTier",
                }
                calibration_fields = {
                    "eligibleToAffectAdvice", "currentEvidence", "heldOutHands",
                    "heldOutDecisions", "minimumHands", "improved", "reason",
                    "sampleSignature", "generatedAt",
                }
                for identity, profile in profiles.items():
                    compact_profile = {
                        key: profile.get(key) for key in profile_fields if key in profile}
                    evidence = profile.get("modelEvidence")
                    if isinstance(evidence, dict):
                        compact_profile["modelEvidence"] = {
                            **{key: evidence.get(key) for key in evidence_fields
                               if key in evidence},
                            "buckets": [
                                {key: bucket.get(key) for key in bucket_fields
                                 if key in bucket}
                                for bucket in evidence.get("buckets", ())
                                if isinstance(bucket, dict)
                            ],
                        }
                    calibration = profile.get("modelCalibration")
                    if isinstance(calibration, dict):
                        compact_profile["modelCalibration"] = {
                            key: calibration.get(key) for key in calibration_fields
                            if key in calibration}
                    compact_profiles[identity] = compact_profile
                snapshot["opponentProfiles"] = compact_profiles
            estimates = snapshot.get("reactionEstimates")
            if isinstance(estimates, dict):
                candidate_fields = {
                    "kind", "ratio", "amount", "reliable", "sampleCount",
                    "populationSampleCount", "minPersonalSamples",
                    "minPopulationSamples", "sampleTier", "matchTier",
                    "fallbackLevel", "probabilities", "callCountDistribution",
                    "expectedCallers", "orderedSeats", "sequential",
                    "personalWeight", "continueFraction",
                    "conditionalEquitySource", "equityByCallers",
                }
                compact_candidates = {}
                for identity, candidate in (estimates.get("candidates") or {}).items():
                    if not isinstance(candidate, dict):
                        continue
                    compact_candidate = {
                        key: candidate.get(key) for key in candidate_fields
                        if key in candidate
                    }
                    if candidate.get("reliable"):
                        compact_candidate["paths"] = [
                            {
                                "probability": path.get("probability"),
                                "outcome": path.get("outcome"),
                                "callers": path.get("callers"),
                                "responses": [
                                    {key: response.get(key) for key in (
                                        "seat", "action", "probability") if key in response}
                                    for response in path.get("responses") or []
                                ],
                            }
                            for path in candidate.get("paths") or []
                        ]
                        compact_candidate["prunedPathProbability"] = candidate.get(
                            "prunedPathProbability")
                    compact_candidates[identity] = compact_candidate
                snapshot["reactionEstimates"] = {
                    "updatedAt": estimates.get("updatedAt"),
                    "reliable": estimates.get("reliable"),
                    "candidates": compact_candidates,
                }
        with self.capture_lock:
            snapshot["frameCapturedAt"] = self.latest_frame_captured_at
            snapshot["frameSequence"] = self.latest_frame_sequence
        if not compact:
            snapshot["frameBuffer"] = self.frame_buffer_status()
        snapshot["stateDeliveredAt"] = time.time()
        if not compact:
            self._flush_action_audits(snapshot)
        return snapshot

    def _record_table_event(self, event, **details):
        self.table_events.append({"time": time.time(), "event": event,
                                  "tableSession": self.table_session, **details})
        del self.table_events[:-30]

    def _begin_table_identity_reacquisition(self):
        if not self.table_identity_reacquiring:
            self.table_identity_previous_number = self.table_number
        self.table_identity_reacquiring = True
        self.table_number = None
        self.table_number_candidate = None
        self.table_number_frames = 0
        self.table_identity_ocr = ""
        self.fields.commit("tableNumber", None, 0, "table_reacquisition", False)

    def _observe_table_number(self, observed_number):
        if not observed_number:
            return None
        if observed_number == self.table_number_candidate:
            self.table_number_frames += 1
        else:
            self.table_number_candidate = observed_number
            self.table_number_frames = 1
        if self.table_number_frames < 2:
            return None
        if not self.table_identity_reacquiring:
            self.table_number = observed_number
            return "confirmed"
        previous_number = self.table_identity_previous_number
        if not previous_number:
            self.table_status = "桌号已识别，但缺少离桌前桌号，暂停建议等待人工确认"
            return "unresolved"
        self.table_identity_reacquiring = False
        self.table_identity_previous_number = None
        if observed_number == previous_number:
            self.table_number = observed_number
            self.table_status = "已返回原牌桌，继续采集"
            self._record_table_event("returned", tableNumber=observed_number)
            return "returned"
        self._reset_for_new_table(observed_number)
        self.table_session += 1
        self.table_status = "已确认换桌，正在重新建立整桌信息"
        self._record_table_event("switched", previousTableNumber=previous_number,
                                 tableNumber=observed_number)
        return "switched"

    def _reset_for_new_table(self, confirmed_table_number=None):
        with self.action_state_lock:
            self._close_action_timeline("table_reset")
            self.action_timeline.reset()
            previous_hand_id = max(int(getattr(self.hand_machine, "hand_id", 0) or 0),
                                   int(self.hand_state.get("id", 0) or 0))
            self.pending.clear()
            self.stable.clear()
            self.seat_trackers.clear()
            if self.action_log:
                self.completed_hand_actions.append({"handId": self.hand_state.get("id"),
                                                    "dealerIndex": self.hand_dealer_index,
                                                    "events": [dict(item) for item in self.action_log]})
            if self.action_candidates:
                self.completed_hand_candidates.append({"handId": self.action_candidates[0].get("handId"),
                                                       "events": [dict(item) for item in self.action_candidates]})
            self._action_event_ledger().close_projection()
            self.action_log.clear()
            self.folded_seats.clear()
            self.action_candidates.clear()
            self.pending_history_events.clear()
            self.fast_action_signatures.clear()
            self.hand_start_capsule_epochs = dict(self.action_capsule_epochs)
            boundary_second = self.hand_started_second
            self.hand_start_visible_capsules = {
                index for index, last_seen in self.action_capsule_last_seen.items()
                if last_seen is not None and boundary_second is not None and
                0 <= boundary_second - last_seen <= 1.0
            }
            self.hand_winners.clear()
            self.previous_actions.clear()
            self.previous_buttons.clear()
            self.pending_hero_buttons.clear()
            self.hero_preselection = None
            self.hero_preselection_candidate = None
            self.hero_preselection_candidate_frame_sequence = None
            self.hero_preselection_candidate_frames = 0
            self.hero_preselection_clear_frames = 0
            self.hero_preselection_clear_frame_sequence = None
            self.action_button_preselection = None
            self.action_button_fragments = None
            self.hand_machine = HandMachine()
            self.hand_machine.hand_id = previous_hand_id
            self.hand_state = {"active": False, "id": previous_hand_id, "street": "waiting", "pot": None,
                               "boardCards": [], "heroCards": []}
            self.hand_dealer_index = None
            self.forced_bet_seats = {}
            self.last_dealer_index = None
            self.participating_locked = False
            self.hand_active = False
            self.hand_closed = False
            self.last_snapshot = None
            self.cached_state = None
            self.history_store.last_signature = None
            self.history_store.hand_profiles.clear()
            self.history_store.session_identities.clear()
            self.history_store.session_hands_by_seat.clear()
            self.profile_confirmed_names.clear()
            self.pending_profile_statistics = None
            self.pending_profile_statistics_queue.clear()
            self.table_number = confirmed_table_number
            self.table_number_candidate = confirmed_table_number
            self.table_number_frames = 2 if confirmed_table_number else 0
            self.table_identity_ocr = ""
            self.table_play = None
            self.blind_amounts = {"small": None, "big": None}
            self.blind_straddle = None
            self.blind_currency = "usd"
            self.blind_text_candidate = None
            self.blind_text_frames = 0
            self.blind_text_raw = ""
            self.blind_ante = None
            self.rake_players = None
            self.rake_source = None
            self.rake_rate = None
            self.rake_cap = None
            self.initial_identity_pending = True
            self.initial_identity_deadline = time.time() + 6.0
            self.force_slow_snapshot = True
            self.slow_refresh_event.set()
            self.locked_hero_cards = []
            self.locked_hero_hand_id = previous_hand_id
            self.hero_cards_present = False
            for field in ("heroCards", "boardCards"):
                self.card_candidates[field] = []
                self.card_candidate_frames[field] = 0
                self.card_published[field] = []
                self.card_visible[field] = []
            self.fast_board_candidate = []
            self.fast_board_frames = 0
            self.center_ocr_cache.clear()
            self.center_ocr_pending_hash = None
            self.center_pot_candidate = None
            self.fields = FieldState()
            self.reaction_estimate_cache_key = None
            self.reaction_estimate_cache = self._empty_reaction_estimates()

    def _frame_copy(self):
        with self.capture_lock:
            return (self.latest_table_frame.copy() if self.latest_table_frame is not None else None,
                    list(self.latest_capture_bbox) if self.latest_capture_bbox else None)

    def _new_capture_context(self, captured_at, frame_sequence, video_second=None):
        return {
            "runtimeId": self.runtime_id,
            "tableSession": self.table_session,
            "handId": self.hand_state.get("id", 0),
            "street": self.hand_state.get("street", "waiting"),
            "observedAt": captured_at,
            "frameSequence": frame_sequence,
            "videoSecond": video_second,
        }

    def _capture_context_for_frame(self, captured_at, frame_sequence, video_second=None,
                                   stored=None):
        context = dict(stored or {})
        if (context.get("runtimeId") != self.runtime_id or
                context.get("tableSession") != self.table_session or
                context.get("frameSequence") != frame_sequence):
            context = self._new_capture_context(captured_at, frame_sequence, video_second)
        return context

    @staticmethod
    def _event_second(event):
        video_second = event.get("videoSecond")
        if video_second is not None:
            recognized_at = event.get("recognizedAt")
            if (isinstance(recognized_at, (int, float)) and
                    (float(video_second) > 1_000_000_000) == (float(recognized_at) > 1_000_000_000) and
                    float(recognized_at) - float(video_second) > 2.0):
                return recognized_at
            return video_second
        return next((event.get(key) for key in ("observedAt", "recognizedAt", "time")
                     if isinstance(event.get(key), (int, float))), None)

    @classmethod
    def _action_reopened_after(cls, events, anchor, actor_seat=None):
        try:
            anchor_index = events.index(anchor)
        except ValueError:
            return False
        hand_id, street = anchor.get("handId"), anchor.get("street")
        actor_seat = anchor.get("seat") if actor_seat is None else actor_seat
        highest = 0.0
        investment_actions = {"blind", "post_blind", "straddle", "call",
                              "bet", "raise", "reraise", "allin"}
        aggressive_actions = {"bet", "raise", "reraise", "allin"}
        for index, item in enumerate(events):
            if item.get("handId") != hand_id or item.get("street") != street:
                continue
            amount = item.get("amount")
            numeric_amount = float(amount) if isinstance(amount, (int, float)) else 0.0
            tolerance = max(.001, highest * .02)
            if (index > anchor_index and item.get("seat") != actor_seat and
                    item.get("action") in aggressive_actions and
                    numeric_amount > highest + tolerance):
                return True
            if item.get("action") in investment_actions:
                highest = max(highest, numeric_amount)
        return False

    def _hero_turn_latched(self):
        return bool(
            self.visual_turn_detected and
            self.visual_turn_hand_id == self.hand_state.get("id") and
            self.visual_turn_street == self.hand_state.get("street")
        )

    def _merge_action_button_fragments(self, buttons, observed_at, frame_sequence):
        if self._official_action_cluster(buttons):
            self.action_button_fragments = None
            return buttons, False
        if not buttons:
            fragment = self.action_button_fragments or {}
            if (fragment.get("handId") != self.hand_state.get("id") or
                    fragment.get("street") != self.hand_state.get("street") or
                    not isinstance(fragment.get("observedAt"), (int, float)) or
                    not isinstance(observed_at, (int, float)) or
                    float(observed_at) - float(fragment["observedAt"]) > .45):
                self.action_button_fragments = None
            return buttons, False
        fragment = self.action_button_fragments or {}
        same_context = (
            fragment.get("handId") == self.hand_state.get("id") and
            fragment.get("street") == self.hand_state.get("street") and
            isinstance(fragment.get("observedAt"), (int, float)) and
            isinstance(observed_at, (int, float)) and
            0 <= float(observed_at) - float(fragment["observedAt"]) <= .45
        )
        merged = self._deduplicate_buttons(
            list(fragment.get("buttons") or []) + list(buttons)
            if same_context else list(buttons))
        if self._official_action_cluster(merged):
            self.action_button_fragments = None
            return merged, same_context
        self.action_button_fragments = {
            "handId": self.hand_state.get("id"),
            "street": self.hand_state.get("street"),
            "observedAt": observed_at,
            "frameSequence": frame_sequence,
            "buttons": merged,
        }
        return buttons, False

    def _hero_button_recovery_reason(self, frame, buttons, hero_index):
        if buttons:
            return "partial_visual_buttons"
        if self.formal_expected_seat == hero_index:
            return "action_chain_expected_hero"
        if self._hero_action_countdown_visible(frame):
            return "hero_countdown"
        hand_id = self.hand_state.get("id")
        street = self.hand_state.get("street")
        hero_seat = hero_index + 1
        uncertain_fold = any(
            item.get("handId") == hand_id and item.get("street") == street and
            item.get("seat") == hero_seat and item.get("action") == "fold" and
            (item.get("orderConflict") or item.get("inferred") or
             float(item.get("confidence") or 0) < ACTION_STRATEGY_CONFIDENCE)
            for item in self.action_log
        )
        if uncertain_fold:
            return "uncertain_hero_fold"
        chain = self._action_chain_snapshot(hand_id, street)
        if hero_seat in set(chain.get("awaitingSeats") or []):
            return "action_chain_awaiting_hero"
        if any(hero_seat in set(item.get("missingSeats") or [])
               for item in chain.get("conflicts") or []):
            return "action_chain_missing_hero"
        return None

    def _retract_hero_fold_contradicted_by_buttons(self, hero_index):
        hand_id = self.hand_state.get("id")
        street = self.hand_state.get("street")
        hero_seat = hero_index + 1
        contradicted = [
            item for item in self.action_log
            if item.get("handId") == hand_id and item.get("street") == street and
            item.get("seat") == hero_seat and item.get("action") == "fold"
        ]
        if not contradicted:
            return False
        self.action_log[:] = [item for item in self.action_log if item not in contradicted]
        self.folded_seats.discard(hero_seat)
        tracker = self.seat_trackers.get(hero_index)
        if tracker is not None:
            tracker.update(lastAction="waiting")
            if tracker.get("visualState") == "fold":
                tracker.update(visualState="unknown", visualStateText="",
                               visualStateConfidence=0.0)
        for candidate in self.action_candidates:
            if (candidate.get("handId") == hand_id and candidate.get("street") == street and
                    candidate.get("seat") == hero_seat and candidate.get("action") == "fold"):
                candidate.update(promoted=False, invalidated=True,
                                 invalidatedBy="official_hero_buttons")
        self._action_event_ledger().sync_projection(
            self.action_log, "official_hero_buttons_retracted_fold")
        chain = self._action_chain_snapshot(hand_id, street)
        missing = next((item.get("missingSeats") or []
                        for item in chain.get("conflicts") or []
                        if item.get("missingSeats")), [])
        self.formal_expected_seat = (int(missing[0]) - 1 if missing else
                                     chain.get("nextActor"))
        return True

    def _hero_buttons_blocked_by_forced_bets(self):
        if (self.hand_state.get("street") != "preflop" or
                not getattr(self, "waiting_for_forced_bets", False)):
            return False
        hero_index = 4 if self.layout == "8max" else 3
        hand_id = self.hand_state.get("id")
        confirmed_blind_seats = {
            item.get("seat") for item in self.action_log
            if item.get("handId") == hand_id and item.get("street") == "preflop" and
            item.get("action") == "blind" and item.get("amount") not in (None, 0)
        }
        return self.formal_expected_seat != hero_index or len(confirmed_blind_seats) < 2

    def _hero_straddle_prompt(self, buttons, hero_index):
        if (self.hand_state.get("street") != "preflop" or
                not any("straddle" in str(button.get("text") or "").lower()
                        for button in buttons)):
            return False
        if self.formal_expected_seat != hero_index:
            return False
        return not any(
            item.get("handId") == self.hand_state.get("id") and
            item.get("street") == "preflop" and
            item.get("seat") == hero_index + 1 and item.get("action") == "straddle"
            for item in self.action_log
        )

    def _confirm_expected_actor_from_hero_turn(self, hero_index, observed_at,
                                               frame_sequence, pot_after=None,
                                               require_immediate=True,
                                               allow_weak_inference=False,
                                               hero_facing_call=False):
        expected = self.formal_expected_seat
        if (expected is None or expected == hero_index or
                require_immediate and self._next_opponent_seat(expected) != hero_index):
            return None
        tracker = self.seat_trackers.get(expected, {})
        if tracker.get("occupancy") != "occupied" or not tracker.get("handEligible", True):
            return None
        hand_id = self.hand_state.get("id")
        street = self.hand_state.get("street")
        current = [item for item in self.action_log
                   if item.get("handId") == hand_id and item.get("street") == street]
        latest_reopen = -1
        running_highest = 0.0
        for index, item in enumerate(current):
            amount = item.get("amount")
            numeric_amount = float(amount) if isinstance(amount, (int, float)) else 0.0
            tolerance = max(.001, running_highest * .02)
            if (item.get("seat") != expected + 1 and
                    item.get("action") in ("bet", "raise", "reraise", "allin") and
                    numeric_amount > running_highest + tolerance):
                latest_reopen = index
            if item.get("action") in ("blind", "post_blind", "straddle", "call",
                                      "bet", "raise", "reraise", "allin"):
                running_highest = max(running_highest, numeric_amount)
        voluntary = next((item for index, item in reversed(list(enumerate(current)))
                          if item.get("seat") == expected + 1 and
                          index > latest_reopen and
                          item.get("action") not in ("blind", "post_blind", "straddle")), None)
        if voluntary is not None:
            return None
        investment_actions = {"blind", "post_blind", "straddle", "call",
                              "bet", "raise", "reraise", "allin"}
        highest = max((float(item.get("amount") or 0) for item in current
                       if item.get("action") in investment_actions), default=0.0)
        logged_amount = max((float(item.get("amount") or 0) for item in current
                             if item.get("seat") == expected + 1 and
                             item.get("action") in investment_actions), default=0.0)
        observed_amount = max(
            logged_amount,
            float(tracker.get("stableBet") or 0),
            float(tracker.get("pendingVisualBet") or 0),
        )
        color_action = self.active_color_actions.get(expected)
        tolerance = max(.001, highest * .02)
        action = None
        amount = 0.0
        increase = 0.0
        evidence = ""
        confidence = .91
        if color_action == "call" and highest > logged_amount + tolerance:
            action, amount = "call", highest
            increase = max(0.0, amount - logged_amount)
            evidence, confidence = "official_hero_turn+prior_call_capsule", .95
        elif (color_action == "check" and not hero_facing_call and
              highest <= logged_amount + tolerance):
            action = "check"
            evidence, confidence = "official_hero_turn+prior_check_capsule", .95
        elif observed_amount > logged_amount + tolerance:
            amount = observed_amount
            increase = max(0.0, amount - logged_amount)
            if amount > highest + tolerance:
                action = "bet" if street != "preflop" and highest <= tolerance else "raise"
                evidence = "official_hero_turn+prior_investment_increased"
            elif amount >= highest - tolerance:
                action = "call"
                evidence = "official_hero_turn+prior_investment_matched"
            elif (tracker.get("visualState") == "allin" or
                  isinstance(tracker.get("chips"), (int, float)) and tracker["chips"] <= .01):
                action = "allin"
                evidence = "official_hero_turn+prior_short_allin"
            else:
                return None
        elif highest > logged_amount + tolerance:
            prior_pot = self.hand_state.get("pot")
            call_deficit = highest - logged_amount
            concurrent_money_event = any(
                item.get("seat") != expected + 1 and
                item.get("action") in investment_actions and
                self._event_second(item) is not None and
                abs(float(self._event_second(item)) - float(observed_at)) <= .05
                for item in current
            )
            pot_delta_proves_call = bool(
                self._next_opponent_seat(expected) == hero_index and
                not concurrent_money_event and
                isinstance(pot_after, (int, float)) and
                isinstance(prior_pot, (int, float)) and
                abs((float(pot_after) - float(prior_pot)) - call_deficit) <=
                max(.01, call_deficit * .08)
            )
            if pot_delta_proves_call:
                action, amount, increase = "call", highest, call_deficit
                evidence, confidence = "official_hero_turn+exact_pot_delta_call", .94
            elif allow_weak_inference:
                action = "fold"
                evidence = "official_hero_turn+prior_call_deficit"
            else:
                return None
        else:
            if not allow_weak_inference:
                return None
            action = "check"
            evidence = "official_hero_turn+prior_bet_already_matched"
        event = {
            "time": time.time(), "observedAt": observed_at,
            "recognizedAt": time.time(), "frameSequence": frame_sequence,
            "videoSecond": getattr(self, "recording_second", None),
            "handId": hand_id, "street": street, "sequence": 1,
            "seat": expected + 1, "name": tracker.get("name", ""),
            "action": action, "amount": amount, "increase": increase,
            "chipsAfter": tracker.get("chips"), "potAfter": pot_after,
            "confidence": confidence, "evidence": evidence,
            "inferred": True, "chainStatus": "rule_confirmed",
            "strategyEligible": True,
        }
        if not self._append_action_event(event, resolve_prior=False):
            return None
        tracker["lastAction"] = action
        if action in ("call", "bet", "raise", "reraise", "allin"):
            tracker["stableBet"] = amount
        return event

    @staticmethod
    def _unique_aggression_uses_pot_delta(buttons):
        call_button = next((item for item in buttons if item.get("kind") == "call"), None)
        return bool(call_button and (
            call_button.get("value") in (None, "allin") or call_button.get("allinCall")
        ))

    def _confirm_unique_aggression_from_hero_button(self, buttons, hero_index,
                                                     observed_at, frame_sequence,
                                                     pot_before=None, pot_after=None,
                                                     pot_confidence=0.0):
        missing = self._hero_turn_probe_seats(hero_index)
        active_aggressors = [seat for seat in missing
                             if self.active_color_actions.get(seat) == "investment"]
        adjacent = (len(missing) == 1 and
                    self._next_opponent_seat(missing[0]) == hero_index)
        leading_visible_aggression = (len(active_aggressors) == 1 and
                                      active_aggressors[0] == missing[0])
        if not missing or not (adjacent or leading_visible_aggression):
            return None
        expected = missing[0]
        tracker = self.seat_trackers.get(expected, {})
        if (tracker.get("occupancy") != "occupied" or not tracker.get("handEligible", True) or
                tracker.get("visualState") == "fold" and
                not self.active_color_actions.get(expected)):
            return None
        hand_id = self.hand_state.get("id")
        street = self.hand_state.get("street")
        explicit_fold = next((item for item in reversed(self.action_candidates)
                              if item.get("handId") == hand_id and item.get("street") == street and
                              item.get("seat") == expected + 1 and item.get("action") == "fold" and
                              item.get("evidenceSignals", {}).get("avatarText") and
                              not item.get("expired")), None)
        if explicit_fold is not None:
            return None
        investments = {"blind", "post_blind", "straddle", "call",
                       "bet", "raise", "reraise", "allin"}
        events = [item for item in self.action_log
                  if item.get("handId") == hand_id and item.get("street") == street and
                  not item.get("orderConflict") and item.get("strategyEligible", True)]
        amounts = {}
        for item in events:
            if item.get("action") not in investments or not isinstance(item.get("amount"), (int, float)):
                continue
            seat = item.get("seat")
            amounts[seat] = max(amounts.get(seat, 0.0), float(item["amount"]))
        highest = max(amounts.values(), default=0.0)
        actor_invested = amounts.get(expected + 1, 0.0)
        hero_invested = amounts.get(hero_index + 1, 0.0)
        tolerance = max(.001, highest * .02)
        call_button = next((item for item in buttons if item.get("kind") == "call"), None)
        if call_button is None:
            return None
        button_value = call_button.get("value")
        if (isinstance(button_value, (int, float)) and
                float(call_button.get("ocrConfidence") or 0) >= .70):
            latest_hero_action = next((
                item for item in reversed(events)
                if item.get("seat") == hero_index + 1 and
                item.get("action") in ("bet", "raise", "reraise") and
                isinstance(item.get("amount"), (int, float))
            ), None)
            if (latest_hero_action is not None and
                    "hero_action_capsule_ocr" in str(latest_hero_action.get("evidence") or "") and
                    isinstance(pot_before, (int, float)) and
                    isinstance(pot_after, (int, float)) and
                    float(pot_confidence or 0) >= .65):
                prior_hero_total = max((
                    float(item["amount"]) for item in events
                    if item is not latest_hero_action and
                    item.get("seat") == hero_index + 1 and
                    item.get("action") in investments and
                    isinstance(item.get("amount"), (int, float))
                ), default=0.0)
                pot_delta = float(pot_after) - float(pot_before)
                corrected_hero = (
                    pot_delta + prior_hero_total + actor_invested - float(button_value)
                ) / 2
                reconstructed_pot = (
                    float(pot_before) + corrected_hero - prior_hero_total +
                    corrected_hero + float(button_value) - actor_invested
                )
                if (corrected_hero > prior_hero_total + .001 and
                        abs(reconstructed_pot - float(pot_after)) <=
                        max(.02, abs(float(pot_after)) * .01) and
                        abs(corrected_hero - float(latest_hero_action["amount"])) >
                        max(.05, corrected_hero * .15)):
                    self._action_event_ledger().sync_projection(
                        self.action_log, "before_hero_amount_pot_cross_check")
                    latest_hero_action.update(
                        amount=round(corrected_hero, 6),
                        increase=round(corrected_hero - prior_hero_total, 6),
                        confidence=max(.95, float(latest_hero_action.get("confidence") or 0)),
                        evidence=(
                            f"{latest_hero_action.get('evidence')}"
                            "+next_hero_button_pot_delta_cross_checked"
                        ),
                        chainStatus="cross_checked", strategyEligible=True,
                        orderConflict=False, inferred=True,
                    )
                    hero_invested = corrected_hero
                    self.seat_trackers.get(hero_index, {}).update(
                        stableBet=corrected_hero)
            amount = hero_invested + float(button_value)
            evidence = "official_numeric_call_button+unique_missing_actor"
            if latest_hero_action is not None and "pot_delta_cross_checked" in str(
                    latest_hero_action.get("evidence") or ""):
                evidence += "+hero_amount_cross_checked"
        elif (button_value == "allin" or call_button.get("allinCall") or
              button_value is None):
            if (not isinstance(pot_before, (int, float)) or
                    not isinstance(pot_after, (int, float)) or
                    float(pot_confidence or 0) < .65):
                return None
            pot_increase = float(pot_after) - float(pot_before)
            if pot_increase <= max(.001, float(pot_before) * .005):
                return None
            amount = actor_invested + pot_increase
            evidence = ("official_allin_button+reliable_pot_delta+unique_missing_actor"
                        if button_value == "allin" or call_button.get("allinCall") else
                        "official_hero_buttons+reliable_pot_delta+unique_missing_actor")
        else:
            return None
        if amount <= highest + tolerance:
            return None
        action = "bet" if street != "preflop" and highest <= tolerance else "raise"
        now = time.time()
        event = {
            "time": now, "observedAt": observed_at, "recognizedAt": now,
            "frameSequence": frame_sequence, "videoSecond": getattr(self, "recording_second", None),
            "handId": hand_id, "street": street, "sequence": 1,
            "seat": expected + 1, "name": tracker.get("name", ""),
            "action": action, "amount": round(amount, 6),
            "increase": round(max(0.0, amount - actor_invested), 6),
            "chipsAfter": tracker.get("chips"), "potAfter": pot_after,
            "confidence": .92, "evidence": evidence, "inferred": True,
            "chainStatus": "rule_confirmed", "strategyEligible": True,
        }
        if not self._append_action_event(event, resolve_prior=False):
            return None
        tracker["lastAction"] = action
        tracker["stableBet"] = amount
        return event

    def _promote_last_action_confirmed_by_hero_buttons(self, hero_index, frame_sequence):
        if self.formal_expected_seat != hero_index:
            return None
        hand_id = self.hand_state.get("id")
        street = self.hand_state.get("street")
        event = ActionEngine.select_fold_confirmed_by_hero_buttons(
            self.action_log, hand_id, street, hero_index, frame_sequence,
            ACTION_STRATEGY_CONFIDENCE)
        if event is None:
            return None
        event["sourceConfidence"] = event.get("confidence")
        event["confidence"] = .88
        event["evidence"] = "avatar_fold_text+legal_order+hero_buttons"
        event["chainStatus"] = "rule_confirmed"
        event["heroButtonConfirmed"] = True
        return event

    def _promote_allin_confirmed_by_equal_amounts(self, buttons, hero_index):
        hand_id = self.hand_state.get("id")
        street = self.hand_state.get("street")
        selection = ActionEngine.select_allin_confirmed_by_call_amount(
            buttons, self.action_log, hand_id, street, hero_index,
            ACTION_STRATEGY_CONFIDENCE, require_later_equal_action=True)
        if selection is None:
            return None
        candidate = selection["candidate"]
        target = selection["target"]
        hero_invested = selection["heroInvested"]
        call_button = selection["callButton"]
        corroborating_action = selection["corroborating"]
        candidate["sourceConfidence"] = candidate.get("confidence")
        candidate["confidence"] = .90
        candidate["evidence"] = (
            f"{candidate.get('evidence') or 'allin_amount'}"
            "+later_equal_amount_action+official_hero_call_amount"
        )
        candidate["chainStatus"] = "cross_checked"
        candidate["equalAmountCrossCheck"] = {
            "target": round(target, 6),
            "corroboratingSeat": corroborating_action.get("seat"),
            "heroPrior": round(hero_invested, 6),
            "heroCall": round(float(call_button["value"]), 6),
        }
        self._publish_confirmed_action_state(candidate)
        self._publish_action_audit(candidate)
        return candidate

    def _promote_allin_confirmed_by_explicit_amount_and_hero_call(self, buttons, hero_index):
        hand_id = self.hand_state.get("id")
        street = self.hand_state.get("street")
        selection = ActionEngine.select_allin_confirmed_by_call_amount(
            buttons, self.action_log, hand_id, street, hero_index,
            ACTION_STRATEGY_CONFIDENCE)
        if selection is None:
            return None
        candidate = selection["candidate"]
        target = selection["target"]
        hero_invested = selection["heroInvested"]
        call_button = selection["callButton"]
        if (isinstance(candidate.get("investmentText"), str) and
                "investment_amount" not in str(candidate.get("evidence") or "").lower() and
                self._extract_investment_amount(candidate["investmentText"]) is None):
            return None
        missing = candidate.get("missingSeatsBefore") or []
        participants = self.hand_participants.get(hand_id, set())
        for missing_seat in missing:
            seat_number = int(missing_seat)
            tracker = self.seat_trackers.get(seat_number - 1, {})
            if ((seat_number - 1) in participants and
                    tracker.get("occupancy") == "occupied" and
                    tracker.get("visualState") not in ("fold", "allin")):
                return None
        candidate["sourceConfidence"] = candidate.get("confidence")
        candidate["confidence"] = .90
        candidate["increase"] = round(max(0.0, target - hero_invested), 6)
        candidate["evidence"] = f"{candidate.get('evidence') or 'allin_text+investment_amount'}+official_hero_call_amount"
        candidate["chainStatus"] = "cross_checked"
        candidate["orderConflict"] = False
        candidate["strategyEligible"] = True
        candidate["explicitAmountCallCrossCheck"] = {
            "target": round(target, 6),
            "heroPrior": round(hero_invested, 6),
            "heroCall": round(float(call_button["value"]), 6),
        }
        ActionLedgerLayer.reorder(
            self.action_log, getattr(self, "hand_dealers", {}), self.hand_participants,
            self.hand_dealer_index, len(TABLE_LAYOUTS[self.layout]))
        self._rebuild_action_timeline(hand_id, street, candidate)
        self._publish_confirmed_action_state(candidate)
        self._publish_action_audit(candidate)
        return candidate

    def _promote_allin_confirmed_by_allin_call(self, buttons, hero_index):
        if (not any(button.get("kind") == "call" and
                        (button.get("value") == "allin" or button.get("allinCall"))
                        for button in buttons)):
            return None
        hand_id = self.hand_state.get("id")
        street = self.hand_state.get("street")
        candidate = ActionEngine.select_allin_confirmed_by_hero_allin_call(
            buttons, self.action_log, hand_id, street)
        if candidate is None:
            return None
        self._action_event_ledger().sync_projection(
            self.action_log, "before_official_allin_cross_check")
        prior = max((float(event.get("amount") or 0) for event in self.action_log
                     if event is not candidate and event.get("handId") == hand_id and
                     event.get("street") == street and
                     event.get("seat") == candidate.get("seat") and
                     event.get("action") in ("call", "bet", "raise", "reraise", "allin")),
                    default=0.0)
        candidate["sourceConfidence"] = candidate.get("confidence")
        candidate["confidence"] = .90
        candidate["increase"] = round(max(0.0, float(candidate["amount"]) - prior), 6)
        candidate["evidence"] = f"{candidate.get('evidence')}+official_hero_allin_call_button"
        candidate["chainStatus"] = "cross_checked"
        candidate["orderConflict"] = False
        candidate["strategyEligible"] = True
        ActionLedgerLayer.reorder(
            self.action_log, getattr(self, "hand_dealers", {}), self.hand_participants,
            self.hand_dealer_index, len(TABLE_LAYOUTS[self.layout]))
        self._rebuild_action_timeline(candidate.get("handId"), candidate.get("street"), candidate)
        self._publish_confirmed_action_state(candidate)
        self._publish_action_audit(candidate)
        return candidate

    def _confirm_unique_raise_from_hero_allin_call(
            self, buttons, decision_chips, hero_index, observed_at, frame_sequence,
            pot_after=None):
        if not any(
            button.get("kind") == "call" and
            (button.get("value") == "allin" or button.get("allinCall"))
            for button in buttons
        ):
            return None
        hand_id = self.hand_state.get("id")
        street = self.hand_state.get("street")
        terminal = {seat - 1 for seat in self.folded_seats}
        terminal.update((item.get("seat") or 1) - 1 for item in self.action_log
                        if item.get("handId") == hand_id and
                        item.get("action") in ("fold", "allin"))
        ambiguous_check = ActionEngine.select_retractable_check_for_allin_call(
            buttons, self.action_log, hand_id, street, hero_index,
            len(TABLE_LAYOUTS[self.layout]), self._current_hand_eligible_indices(),
            terminal)
        if ambiguous_check is not None:
            self._action_event_ledger().sync_projection(
                self.action_log, "before_ambiguous_check_retraction")
            self.action_log.remove(ambiguous_check)
            expected = int(ambiguous_check["seat"]) - 1
            self.formal_expected_seat = expected
            tracker = self.seat_trackers.get(expected)
            if tracker is not None:
                tracker["lastAction"] = "waiting"
            self._commit_formal_action_ledger({"handId": hand_id, "street": street})
        chain = self._action_chain_snapshot(
            hand_id, street)
        expected = chain.get("nextActor")
        awaiting = chain.get("awaitingSeats") or []
        if ((not chain.get("reliable") and ambiguous_check is None) or expected is None or
                awaiting != [expected + 1] or
                self._next_opponent_seat(expected) != hero_index):
            return None
        tracker = self.seat_trackers.get(expected, {})
        if (tracker.get("occupancy") != "occupied" or
                not tracker.get("handEligible", True) or
                tracker.get("visualState") in ("fold", "away", "empty")):
            return None
        hero_stack = (decision_chips or {}).get(str(hero_index), {})
        reliable_hero_stack = bool(
            hero_stack.get("ledgerEvidenceReliable") or
            hero_stack.get("source") == "same_frame_seat_stack_fallback" and
            float(hero_stack.get("confidence") or 0) >= .95
        )
        if (not isinstance(hero_stack.get("value"), (int, float)) or
                float(hero_stack.get("value")) <= 0 or
                float(hero_stack.get("confidence") or 0) < ACTION_STRATEGY_CONFIDENCE or
                not reliable_hero_stack):
            return None
        investments = {"blind", "post_blind", "straddle", "call",
                       "bet", "raise", "reraise", "allin"}
        current = [event for event in self.action_log
                   if event.get("handId") == hand_id and event.get("street") == street and
                   not event.get("orderConflict") and event.get("strategyEligible", True)]
        amounts = {}
        for event in current:
            if (event.get("action") not in investments or
                    not isinstance(event.get("amount"), (int, float))):
                continue
            amounts[event.get("seat")] = max(
                amounts.get(event.get("seat"), 0.0), float(event["amount"]))
        highest = max(amounts.values(), default=0.0)
        actor_invested = amounts.get(expected + 1, 0.0)
        hero_invested = amounts.get(hero_index + 1, 0.0)
        minimum_total = hero_invested + float(hero_stack["value"])
        tolerance = max(.01, highest * .02)
        if minimum_total <= highest + tolerance:
            return None
        action = "bet" if street != "preflop" and highest <= tolerance else "raise"
        now = time.time()
        event = {
            "time": now, "observedAt": observed_at, "recognizedAt": now,
            "frameSequence": frame_sequence,
            "videoSecond": getattr(self, "recording_second", None),
            "handId": hand_id, "street": street, "sequence": 1,
            "seat": expected + 1, "name": tracker.get("name", ""),
            "action": action, "amount": round(minimum_total, 6),
            "increase": round(max(0.0, minimum_total - actor_invested), 6),
            "chipsAfter": tracker.get("chips"), "potAfter": pot_after,
            "confidence": .90, "inferred": True,
            "chainStatus": "rule_confirmed", "strategyEligible": True,
            "evidence": (
                "official_hero_allin_call_button+reliable_hero_stack"
                "+unique_missing_actor"
            ),
            "amountLowerBound": True, "pendingExactAmount": True,
        }
        previous_expected = self.formal_expected_seat
        self.formal_expected_seat = expected
        if not self._append_action_event(event, resolve_prior=False):
            self.formal_expected_seat = previous_expected
            return None
        self.formal_expected_seat = hero_index
        event["nextExpectedSeat"] = hero_index + 1
        tracker["lastAction"] = action
        tracker["stableBet"] = minimum_total
        return event

    @staticmethod
    def _reconcile_pending_allin_call_pot(
            pot, pot_confidence, pot_before_button, pending_action):
        if (not pending_action or
                not pending_action.get("pendingExactAmount") or
                not pending_action.get("amountLowerBound") or
                not isinstance(pot_before_button, (int, float)) or
                pot_before_button < 0 or
                not isinstance(pending_action.get("increase"), (int, float)) or
                pending_action["increase"] <= 0):
            return pot, pot_confidence
        if isinstance(pot, (int, float)):
            pending_action["potAfter"] = float(pot)
            return pot, pot_confidence
        pot = round(float(pot_before_button) + float(pending_action["increase"]), 6)
        pot_confidence = .90
        pending_action["potReconciled"] = True
        pending_action["potEvidence"] = "prior_pot+pending_allin_call_increase"
        pending_action["potAfter"] = float(pot)
        return pot, pot_confidence

    @staticmethod
    def _button_opportunity(buttons, hand_id, street):
        kinds = tuple(sorted({button.get("kind") for button in buttons if button.get("kind")}))
        call = next((button for button in buttons if button.get("kind") == "call"), None)
        value = call.get("value") if call else None
        return {"handId": hand_id, "street": street, "kinds": kinds,
                "call": float(value) if isinstance(value, (int, float)) else value}

    @staticmethod
    def _same_button_opportunity(first, second):
        if (not first or not second or first.get("handId") != second.get("handId") or
                first.get("street") != second.get("street") or
                first.get("kinds") != second.get("kinds") or
                first.get("heroActionCount") != second.get("heroActionCount") or
                Api._button_money_changed(first, second) or
                not Api._button_gap_is_same_opportunity(first, second) or
                Api._confirmed_action_after_button(first, second)):
            return False
        left, right = first.get("call"), second.get("call")
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            return abs(float(left) - float(right)) <= max(.01, abs(float(left)) * .02)
        return left in (None, "allin") or right in (None, "allin") or left == right

    @staticmethod
    def _same_unresolved_button_opportunity(first, second):
        return bool(
            first and second and
            first.get("handId") == second.get("handId") and
            first.get("street") == second.get("street") and
            first.get("heroActionCount") == second.get("heroActionCount") and
            not Api._button_money_changed(first, second) and
            Api._button_gap_is_same_opportunity(first, second) and
            not Api._confirmed_action_after_button(first, second)
        )

    @staticmethod
    def _button_money_changed(first, second):
        for key in ("pot", "heroInvested"):
            left, right = first.get(key), second.get(key)
            if (isinstance(left, (int, float)) and isinstance(right, (int, float)) and
                    abs(float(left) - float(right)) > max(.01, abs(float(left)) * .02)):
                return True
        return False

    @staticmethod
    def _button_gap_is_same_opportunity(first, second):
        first_at, second_at = first.get("capturedAt"), second.get("capturedAt")
        if isinstance(first_at, (int, float)) and isinstance(second_at, (int, float)):
            return 0 <= float(second_at) - float(first_at) <= 2.0
        return True

    @staticmethod
    def _confirmed_action_after_button(first, second):
        button_frame = first.get("frameSequence")
        action_frame = second.get("latestConfirmedActionFrameSequence")
        return (isinstance(button_frame, int) and isinstance(action_frame, int) and
                action_frame > button_frame)

    def _confirm_hero_check_before_next_action(self, event):
        hero_index = 4 if self.layout == "8max" else 3
        context = getattr(self, "hero_button_release_context", None)
        tracker_amount = float(self.seat_trackers.get(hero_index, {}).get("stableBet") or 0)
        if not ActionEngine.prove_hero_check_before_later_action(
                event, context, self.action_log, hero_index,
                self.formal_expected_seat, tracker_amount):
            return False
        repaired = {
            "time": time.time(), "observedAt": context.get("observedAt"),
            "videoSecond": context.get("videoSecond"),
            "frameSequence": context.get("lastVisibleFrameSequence"),
            "handId": event.get("handId"), "street": event.get("street"),
            "seat": hero_index + 1,
            "name": self.seat_trackers.get(hero_index, {}).get("name", "Zixia888"),
            "action": "check", "amount": 0.0, "increase": 0.0,
            "confidence": .95, "inferred": True,
            "chainStatus": "rule_confirmed", "strategyEligible": True,
            "actionButtonSequence": context.get("actionButtonSequence"),
            "evidence": "official_check_button_disappeared+next_opponent_action",
        }
        if not self._append_action_event(repaired, resolve_prior=False):
            return False
        self.seat_trackers.get(hero_index, {}).update(lastAction="check")
        self.hero_button_release_context = None
        return True

    def _hero_turn_probe_seats(self, hero_index):
        expected = self.formal_expected_seat
        seats = []
        for _ in range(len(TABLE_LAYOUTS[self.layout])):
            if expected is None or expected == hero_index or expected in seats:
                break
            seats.append(expected)
            expected = self._next_opponent_seat(expected)
        return seats

    def _current_street_chain_gap_contexts(self):
        hand_id = self.hand_state.get("id")
        street = self.hand_state.get("street")
        contexts = {}
        for item in self.action_log:
            if (item.get("handId") != hand_id or item.get("street") != street or
                    not item.get("orderConflict")):
                continue
            missing = item.get("missingSeatsBefore") or []
            for seat in missing:
                if not isinstance(seat, int) or seat <= 0:
                    continue
                index = seat - 1
                if index in contexts:
                    continue
                contexts[index] = {
                    "seatIndex": index,
                    "conflictSeat": item.get("seat"),
                    "conflictAction": item.get("action"),
                    "conflictSequence": item.get("sequence"),
                    "conflictObservedAt": item.get("observedAt"),
                    "conflictVideoSecond": item.get("videoSecond"),
                    "conflictFrameSequence": item.get("frameSequence"),
                    "actionRound": (
                        item.get("capturedActionRound") or
                        item.get("timeMatchedActionRound") or
                        item.get("actionRound")
                    ),
                    "timeWindowId": (
                        item.get("capturedTimeWindowId") or
                        item.get("timeWindowId")
                    ),
                    "missingSeatsBefore": list(missing),
                }
            if not missing and item.get("seat"):
                index = int(item["seat"]) - 1
                contexts.setdefault(index, {
                    "seatIndex": index,
                    "conflictSeat": item.get("seat"),
                    "conflictAction": item.get("action"),
                    "conflictSequence": item.get("sequence"),
                    "conflictObservedAt": item.get("observedAt"),
                    "conflictVideoSecond": item.get("videoSecond"),
                    "conflictFrameSequence": item.get("frameSequence"),
                    "actionRound": (
                        item.get("capturedActionRound") or
                        item.get("timeMatchedActionRound") or
                        item.get("actionRound")
                    ),
                    "timeWindowId": (
                        item.get("capturedTimeWindowId") or
                        item.get("timeWindowId")
                    ),
                    "missingSeatsBefore": [],
                })
        return contexts

    def _current_street_chain_gap_seats(self):
        return sorted(self._current_street_chain_gap_contexts())

    @staticmethod
    def _bind_chain_gap_repair_event(event, result, context):
        event["rawObservedAt"] = event.get("observedAt")
        event["rawVideoSecond"] = event.get("videoSecond")
        event["rawFrameSequence"] = event.get("frameSequence")
        event["delayedEvidenceRecognizedAt"] = result.get("recognizedAt")
        event["delayedEvidenceFrameSequence"] = result.get("frameSequence")
        event["historicalEvidenceBinding"] = True
        observed_at = context.get("conflictObservedAt")
        video_second = context.get("conflictVideoSecond")
        frame_sequence = context.get("conflictFrameSequence")
        if observed_at is not None:
            event["observedAt"] = observed_at
        if video_second is not None:
            event["videoSecond"] = video_second
        elif observed_at is not None and observed_at < 1_000_000_000:
            event["videoSecond"] = observed_at
        if frame_sequence is not None:
            event["frameSequence"] = frame_sequence
        event["capturedActionRound"] = context.get("actionRound")
        event["capturedTimeWindowId"] = context.get("timeWindowId")
        event["chainGapConflictSeat"] = context.get("conflictSeat")
        event["chainGapConflictSequence"] = context.get("conflictSequence")
        event["chainGapMissingSeatsBefore"] = list(
            context.get("missingSeatsBefore") or [])

    def _prior_street_probe_seats(self):
        prior = getattr(self, "prior_street_unresolved", None)
        if not prior:
            return []
        seats = set(prior.get("seats", set())) & set(prior.get("forcedFoldSeats", set()))
        seats.update(
            (item.get("seat") or 1) - 1
            for item in self.action_candidates
            if item.get("handId") == self.hand_state.get("id") and
            item.get("street") == prior.get("street") and
            item.get("action") == "allin_amount_unresolved" and
            not item.get("promoted")
        )
        return sorted(seats & set(prior.get("seats", set())))

    def _accept_action_result_after_hero_turn(self, result, hero_index,
                                              button_frame_boundary):
        if button_frame_boundary is None:
            return True
        result_frame = result.get("frameSequence")
        if result_frame is not None and result_frame <= button_frame_boundary:
            return True
        if result.get("index") == hero_index:
            candidate = next((
                item for item in reversed(self.action_candidates)
                if item.get("handId") == result.get("handId") and
                item.get("street") == result.get("street") and
                item.get("seat") == hero_index + 1 and
                item.get("action") == "hero_action_unresolved" and
                not item.get("promoted") and not item.get("expired")
            ), None)
            if candidate is None:
                return False
            action = result.get("action")
            if result.get("avatarState") in ("fold", "allin"):
                action = result["avatarState"]
            allowed = set(candidate.get("possibleActions") or [])
            if action in ("bet", "raise", "reraise", "allin"):
                action = "custom_raise"
            if action not in allowed:
                return False
            disappeared_frame = candidate.get("buttonDisappearedFrameSequence")
            if (result_frame is not None and disappeared_frame is not None and
                    result_frame < disappeared_frame):
                return False
            result_second = self._event_second(result)
            disappeared_second = candidate.get("buttonDisappearedSecond")
            if disappeared_second is None:
                disappeared_second = candidate.get("observedAt")
            return bool(
                result_second is not None and disappeared_second is not None and
                0 <= float(result_second) - float(disappeared_second) <= 1.5
            )
        if result.get("priorStreetProbe"):
            return True
        if result.get("chainGapProbe"):
            return result.get("index") in self._current_street_chain_gap_seats()
        if not result.get("expectedActionProbe"):
            return False
        return result.get("index") in self._hero_turn_probe_seats(hero_index)

    def _probe_ocr_pending(self, probe_seats):
        seats = set(probe_seats)
        with self.action_ocr_pending_lock:
            if seats & self.action_ocr_pending_seats:
                return True
        with self.avatar_ocr_pending_lock:
            return bool(seats & self.avatar_ocr_pending_seats)

    def _confirm_adjacent_terminal_text(self, frame, probe_seats, hero_index,
                                        observed_at, frame_sequence):
        if (len(probe_seats) != 1 or
                self._next_opponent_seat(probe_seats[0]) != hero_index):
            return None
        return self._confirm_terminal_text_for_seat(
            frame, probe_seats[0], observed_at, frame_sequence)

    def _confirm_probe_terminal_texts(self, frame, probe_seats,
                                      observed_at, frame_sequence):
        events = []
        for expected in probe_seats:
            if self.formal_expected_seat != expected:
                break
            event = self._confirm_terminal_text_for_seat(
                frame, expected, observed_at, frame_sequence)
            if event is None:
                break
            events.append(event)
        return events

    def _confirm_terminal_text_for_seat(self, frame, expected,
                                        observed_at, frame_sequence):
        tracker = self.seat_trackers.get(expected, {})
        if tracker.get("occupancy") != "occupied" or not tracker.get("handEligible", True):
            return None
        height, width = frame.shape[:2]
        box = self._seat_slot_box(expected, "avatar", width, height)
        if not box:
            return None
        x1, y1, x2, y2 = box
        crop = frame[max(0, y1):min(height, y2), max(0, x1):min(width, x2)]
        if crop.size == 0:
            return None
        line = crop[int(crop.shape[0] * .25):int(crop.shape[0] * .65)]
        text, confidence = self._button_ocr_line(cv2.resize(
            line, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC))
        normalized = str(text).lower().replace(" ", "")
        if self.avatar_state_classifier is not None:
            classified_state = self.avatar_state_classifier._state_from_text(
                str(text), confidence)
            if classified_state in ("fold", "allin"):
                normalized = classified_state
        if ("弃牌" in normalized or "fold" in normalized) and confidence >= .72:
            action = "fold"
        elif self._avatar_text_is_allin(normalized, expected_actor=True) and confidence >= .82:
            action = "allin"
        elif self._model_fold_confirmed_by_later_action(expected):
            action = "fold"
            confidence = .9
        else:
            return None
        event = {
            "time": time.time(), "observedAt": observed_at,
            "recognizedAt": time.time(), "frameSequence": frame_sequence,
            "videoSecond": getattr(self, "recording_second", None),
            "handId": self.hand_state.get("id"), "street": self.hand_state.get("street"),
            "sequence": 1, "seat": expected + 1, "name": tracker.get("name", ""),
            "action": action, "amount": (tracker.get("stableBet", 0.0)
                                           if action == "fold" else None),
            "increase": 0 if action == "fold" else None,
            "chipsAfter": tracker.get("chips"), "confidence": max(.9, confidence),
            "evidence": "official_hero_turn+adjacent_terminal_text",
            "inferred": not bool(normalized),
            "chainStatus": "direct_confirmed", "strategyEligible": action == "fold",
        }
        if not self._append_action_event(event, resolve_prior=True):
            return None
        tracker["lastAction"] = action
        if action == "allin":
            tracker["visualState"] = "allin"
        return event

    def _model_fold_confirmed_by_later_action(self, expected):
        hand_id = self.hand_state.get("id")
        street = self.hand_state.get("street")
        candidate = next((item for item in reversed(self.action_candidates)
                          if item.get("handId") == hand_id and
                          item.get("street") == street and
                          item.get("seat") == expected + 1 and
                          item.get("action") == "fold" and
                          item.get("evidenceFrames", 0) >= 2 and
                          item.get("evidenceSignals", {}).get("avatarModel") and
                          not item.get("expired")), None)
        if candidate is None:
            return False
        candidate_second = self._event_second(candidate)
        return any(
            item.get("handId") == hand_id and item.get("street") == street and
            item.get("seat") != expected + 1 and
            item.get("action") not in ("blind", "post_blind", "straddle") and
            float(item.get("confidence") or 0) >= ACTION_STRATEGY_CONFIDENCE and
            (candidate_second is None or self._event_second(item) is None or
             self._event_second(item) >= candidate_second)
            for item in self.action_log
        )

    def _repair_rule_proven_folds_before_action(self, event, chain):
        if (event.get("action") in ("fold", "blind", "post_blind", "straddle") or
                float(event.get("confidence") or 0) < ACTION_STRATEGY_CONFIDENCE):
            return False
        missing = next((item.get("missingSeats") or []
                        for item in chain.get("conflicts") or []
                        if item.get("reason") == "action_order_gap" and
                        item.get("seat") == event.get("seat") and
                        item.get("missingSeats")), [])
        if not missing:
            return False
        repaired = False
        event_second = self._event_second(event)
        selected = ActionEngine.select_unmatched_price_folds(
            event, missing, self.action_log, self.seat_trackers)
        for repair in selected:
            seat = repair["seat"]
            index = seat - 1
            tracker = self.seat_trackers.get(index, {})
            fold = {
                "time": time.time(),
                "observedAt": None if event_second is None else float(event_second) - .001,
                "videoSecond": None if event_second is None else float(event_second) - .001,
                "handId": event.get("handId"), "street": event.get("street"),
                "seat": seat, "name": tracker.get("name", ""),
                "action": "fold", "amount": repair["amount"], "increase": 0.0,
                "confidence": .9, "inferred": True,
                "chainStatus": "rule_confirmed", "strategyEligible": True,
                "evidence": "later_confirmed_action+unmatched_price_rule_fold",
            }
            if self._append_action_event(fold, resolve_prior=False):
                tracker["lastAction"] = "fold"
                repaired = True
        return repaired

    def _capture_fast_state(self):
        fast_state_started_at = time.time()
        fast_stage_started_at = time.perf_counter()
        fast_stage_ms = {}
        with self.capture_lock:
            frame = self.latest_table_frame.copy() if self.latest_table_frame is not None else None
            frame_captured_at = self.latest_frame_captured_at
            frame_video_second = self.latest_frame_video_second
            frame_sequence = self.latest_frame_sequence
            stored_capture_context = dict(self.latest_frame_context or {})
        if frame is None:
            return None
        capture_context = self._capture_context_for_frame(
            frame_captured_at, frame_sequence, frame_video_second,
            stored_capture_context)
        captured_hand_id = capture_context["handId"]
        state_street = capture_context["street"]
        if (capture_context["runtimeId"] != self.runtime_id or
                capture_context["tableSession"] != self.table_session or
                captured_hand_id != self.hand_state.get("id") or
                state_street != self.hand_state.get("street")):
            return None
        if self.table_identity_reacquiring:
            self.action_button_fragments = None
            return {
                "specialScene": "table_identity_pending", "visualHeroTurn": False,
                "visualButtons": [], "buttons": [], "heroTurn": False,
                "actionable": False, "reliable": False, "spectator": True,
                "actionLog": list(self.action_log),
                "reactionEstimates": self._empty_reaction_estimates(),
                "fastActionEvents": [], "fastUpdatedAt": time.time(),
            }
        height, width = frame.shape[:2]
        self._drain_center_ocr_results()
        pot_before_button = self.hand_state.get("pot")
        center_hash = self._enqueue_center_ocr(
            frame, frame_captured_at, frame_sequence, capture_context)
        scene_frame = frame
        if width > 480:
            scene_frame = cv2.resize(frame, (480, max(200, round(height * 480 / width))),
                                     interpolation=cv2.INTER_AREA)
        special_scene = self._detect_special_scene(scene_frame)
        if special_scene:
            self.action_button_fragments = None
            scene_clock = frame_captured_at if isinstance(frame_captured_at, (int, float)) else time.time()
            cooldown = .15 if special_scene == "community_card_deal" else .75
            self.special_scene_blocked_until = scene_clock + cooldown
            if special_scene != "community_card_deal":
                self.special_scene_last_frame_sequence = max(
                    self.special_scene_last_frame_sequence, frame_sequence or -1)
                self._discard_action_ocr_results()
            return {"specialScene": special_scene, "visualHeroTurn": False, "visualButtons": [],
                    "buttons": [], "heroTurn": False, "actionable": False,
                    "actionLog": list(self.action_log),
                    "actionCandidates": self.action_candidates[-30:],
                    "reactionEstimates": self._empty_reaction_estimates(),
                    "fastActionEvents": [],
                    "fastUpdatedAt": time.time()}
        scene_clock = frame_captured_at if isinstance(frame_captured_at, (int, float)) else time.time()
        if scene_clock < getattr(self, "special_scene_blocked_until", 0.0):
            self.action_button_fragments = None
            return {"specialScene": "scene_blocked", "visualHeroTurn": False,
                    "visualButtons": [], "buttons": [], "heroTurn": False,
                    "actionable": False, "actionLog": list(self.action_log),
                    "actionCandidates": self.action_candidates[-30:],
                    "reactionEstimates": self._empty_reaction_estimates(),
                    "fastActionEvents": [], "fastUpdatedAt": time.time()}
        hero_index = 4 if self.layout == "8max" else 3
        buttons = self._recognize_action_buttons_visual(frame)
        button_recognition_source = "visual"
        buttons, fragments_merged = self._merge_action_button_fragments(
            buttons, frame_captured_at, frame_sequence)
        if fragments_merged:
            button_recognition_source = "visual_multiframe"
        fast_stage_ms["buttons"] = round((time.perf_counter() - fast_stage_started_at) * 1000, 1)
        if (captured_hand_id != self.hand_state.get("id") or
                state_street != self.hand_state.get("street")):
            return None
        turn_confirmed = self._official_action_cluster(buttons)
        if turn_confirmed:
            hero_cards = list(self.card_published.get("heroCards", []))
            visible_hero_cards = list(self.card_visible.get("heroCards", []))
            if len(hero_cards) != 2 or visible_hero_cards != hero_cards:
                hero_box = self._reviewed_slot_box((315, 1570, 575, 1745), width, height)
                hero_region = frame[hero_box[1]:hero_box[3], hero_box[0]:hero_box[2]]
                self._card_recognition_field = "heroCards"
                button_hero_cards = self._recognize_cards_fast(hero_region)[:2]
                self._card_recognition_field = "unknown"
                button_hero_cards = button_hero_cards if len(button_hero_cards) == 2 else []
                with self.card_state_lock:
                    self.card_visible["heroCards"] = list(button_hero_cards)
                    self.card_visible_frame_sequence = frame_sequence
                self._commit_card_observation(
                    "heroCards", button_hero_cards, frame_captured_at,
                    frame_sequence=frame_sequence, hand_id=captured_hand_id)
                hero_cards = list(self.card_published.get("heroCards", []))
                visible_hero_cards = list(self.card_visible.get("heroCards", []))
            turn_confirmed = len(hero_cards) == 2 and visible_hero_cards == hero_cards
        incomplete_call = any(
            button.get("kind") == "call" and
            not isinstance(button.get("value"), (int, float)) and
            button.get("value") != "allin" for button in buttons)
        initial_ledger_call = self._confirmed_ledger_call_amount(hero_index)
        if (incomplete_call and
                (self.formal_expected_seat == hero_index or initial_ledger_call is not None)):
            buttons = self._recognize_visual_button_values(frame, buttons)
            turn_confirmed = self._official_action_cluster(buttons)
            if (turn_confirmed and any(
                    button.get("kind") == "call" and
                    (isinstance(button.get("value"), (int, float)) or
                     button.get("value") == "allin") for button in buttons)):
                button_recognition_source = "visual_official_call_amount"
        elif incomplete_call:
            turn_confirmed = False
            button_recognition_source = "visual_amount_waiting_for_action_chain"
        if (turn_confirmed and any(
                button.get("kind") == "call" and
                not isinstance(button.get("value"), (int, float)) and
                button.get("value") != "allin" for button in buttons)):
            ledger_call = self._confirmed_ledger_call_amount(hero_index)
            if ledger_call is not None:
                buttons = [({**button, "value": ledger_call, "text": f"ledger:{ledger_call:g}",
                             "confidence": max(.9, float(button.get("confidence") or 0))}
                            if button.get("kind") == "call" and not button.get("allinCall")
                            else button) for button in buttons]
            if any(button.get("kind") == "call" and
                   not isinstance(button.get("value"), (int, float)) and
                   button.get("value") != "allin" for button in buttons):
                turn_confirmed = False
                button_recognition_source = "visual_amount_pending"
        if turn_confirmed and self._hero_straddle_prompt(buttons, hero_index):
            self._append_action_candidate({
                "handId": self.hand_state.get("id"), "street": "preflop",
                "seat": hero_index + 1, "action": "hero_straddle_prompt",
                "visualKinds": sorted({button.get("kind") for button in buttons}),
                "frameSequence": frame_sequence, "observedAt": frame_captured_at,
                "evidence": "explicit_straddle_prompt_before_post",
            })
            buttons = []
            turn_confirmed = False
            button_recognition_source = "straddle_prompt"
        fallback_attempted = False
        fallback_clock = time.monotonic()
        recovery_reason = (None if button_recognition_source ==
                           "visual_amount_waiting_for_action_chain" else
                           self._hero_button_recovery_reason(frame, buttons, hero_index))
        if (not turn_confirmed and recovery_reason and
                self.hand_state.get("active") and
                (recovery_reason == "uncertain_hero_fold" or
                 not self._betting_round_closed()) and
                frame_sequence != self.button_ocr_fallback_last_frame_sequence and
                fallback_clock - self.button_ocr_fallback_last_at >= .18):
            fallback_attempted = True
            self.button_ocr_fallback_last_at = fallback_clock
            self.button_ocr_fallback_last_frame_sequence = frame_sequence
            fallback_buttons = self._recognize_action_buttons_fast(frame)
            combined_buttons = self._deduplicate_buttons(buttons + fallback_buttons)
            combined_buttons, fallback_fragments_merged = self._merge_action_button_fragments(
                combined_buttons, frame_captured_at, frame_sequence)
            hero_cards = list(self.card_published.get("heroCards", []))
            visible_hero_cards = list(self.card_visible.get("heroCards", []))
            if (self._official_action_cluster(combined_buttons) and len(hero_cards) == 2 and
                    visible_hero_cards == hero_cards):
                buttons = combined_buttons
                turn_confirmed = True
                button_recognition_source = f"recovery_ocr:{recovery_reason}"
                if fallback_fragments_merged:
                    button_recognition_source += "+multiframe"
        board_band = frame[int(height * .38):int(height * .62), int(width * .18):int(width * .82)]
        board_count = self._count_card_boxes(board_band)
        with self.card_state_lock:
            card_visible_sequence = self.card_visible_frame_sequence
        published_board = list(self.card_published.get("boardCards", []))
        if (isinstance(card_visible_sequence, int) and card_visible_sequence > frame_sequence and
                len(published_board) > board_count):
            # A slow card worker has already advanced the shared street using
            # a newer frame while this scan is still processing an older one.
            # Do not bind the old frame's buttons to the new street.
            return None
        if (len(published_board) > board_count and
                len(published_board) in (3, 4, 5) and
                len(set(published_board)) == len(published_board)):
            return None
        previous_board = self.hand_state.get("boardCards", [])
        board_progression = {0: {3}, 3: {4, 5}, 4: {5}}
        street_transition_pending = board_count in board_progression.get(len(previous_board), set())
        if street_transition_pending:
            turn_confirmed = False
            buttons = []
        button_context_street = self.hand_state.get("street")
        if turn_confirmed and street_transition_pending:
            button_context_street = {3: "flop", 4: "turn", 5: "river"}.get(
                board_count, button_context_street)
        fast_events = self._drain_action_ocr_results(
            hero_buttons_visible=turn_confirmed,
            hero_button_frame_sequence=frame_sequence)
        if (turn_confirmed and not street_transition_pending and
                board_count == len(previous_board) and self._betting_round_closed()):
            self._append_action_candidate({
                "handId": self.hand_state.get("id"), "street": self.hand_state.get("street"),
                "seat": hero_index + 1, "action": "hero_buttons_blocked_closed_round",
                "visualKinds": sorted({button.get("kind") for button in buttons}),
                "frameSequence": frame_sequence, "observedAt": frame_captured_at,
                "evidence": "betting_round_closed_before_next_street_cards",
            })
            buttons = []
            turn_confirmed = False
            button_recognition_source = "blocked_closed_round"
        elif fallback_attempted and not turn_confirmed:
            self._append_action_candidate({
                "handId": self.hand_state.get("id"), "street": self.hand_state.get("street"),
                "seat": hero_index + 1, "action": "hero_button_recovery_unconfirmed",
                "visualKinds": sorted({button.get("kind") for button in buttons}),
                "frameSequence": frame_sequence, "observedAt": frame_captured_at,
                "recoveryReason": recovery_reason,
                "evidence": "redundant_trigger+visual_cluster_incomplete+ocr_fallback_unconfirmed",
            })
        previous_button_frame_sequence = self.hero_button_last_visible_frame_sequence
        if turn_confirmed:
            self._retract_hero_fold_contradicted_by_buttons(hero_index)
            self.hero_button_last_visible_frame_sequence = frame_sequence
            self.hero_button_last_visible_hand_id = self.hand_state.get("id")
            self.hero_button_last_visible_street = button_context_street
        possible_hand_reset = (len(previous_board) >= 3 and board_count == 0 and
                               len(self.fast_board_candidate) != len(previous_board))
        board_shape_stable = (board_count == len(previous_board) or
                              (board_count == 0 and len(self.fast_board_candidate) == len(previous_board)))
        if not turn_confirmed and board_shape_stable and not (self.hand_state.get("id", 0) <= 0 or possible_hand_reset or
                street_transition_pending or self.fast_dealer_changed or self.hand_closed):
            fast_events.extend(self._capture_fast_actions_for_frame(
                frame, self.hand_state.get("pot"), capture_context))
            if self.action_ocr_queue.unfinished_tasks:
                action_deadline = time.time() + .03
                while self.action_ocr_queue.unfinished_tasks and time.time() < action_deadline:
                    time.sleep(.001)
                fast_events.extend(self._drain_action_ocr_results())
        actions_scanned_at = time.time()
        if turn_confirmed:
            probe_seats = self._hero_turn_probe_seats(hero_index)
            ordinary_call_visible = any(
                button.get("kind") == "call" and not button.get("allinCall")
                for button in buttons)
            ledger_evidence = self._confirmed_ledger_call_amount(hero_index)
            if ordinary_call_visible and (
                    self.formal_expected_seat == hero_index or ledger_evidence is not None):
                buttons = self._recognize_visual_button_values(frame, buttons)
                turn_confirmed = self._official_action_cluster(buttons)
            ledger_call = None if probe_seats else ledger_evidence
            visual_call = next((button for button in buttons
                                if button.get("kind") == "call" and
                                not button.get("allinCall")), None)
            visual_call_reliable = bool(
                visual_call and isinstance(visual_call.get("value"), (int, float)) and
                float(visual_call.get("ocrConfidence") or 0) >= .85)
            if ledger_call is not None and visual_call and not visual_call_reliable:
                buttons = [({**button, "value": ledger_call, "text": f"ledger:{ledger_call:g}",
                             "confidence": max(.9, float(button.get("confidence") or 0))}
                            if button.get("kind") == "call" and not button.get("allinCall")
                            else button) for button in buttons]
        hero_cards = list(self.card_published.get("heroCards", []))
        visible_hero_cards = list(self.card_visible.get("heroCards", []))
        board_cards = list(self.card_published.get("boardCards", []))
        visible_board_cards = list(self.card_visible.get("boardCards", []))
        confirmed_board = list(board_cards)
        with self.action_state_lock:
            if (captured_hand_id != self.hand_state.get("id") or
                    state_street != self.hand_state.get("street")):
                return None
            turn_context_changed = (
                self.visual_turn_hand_id != self.hand_state.get("id") or
                self.visual_turn_street != button_context_street
            )
            button_reappeared_after_gap = bool(
                turn_confirmed and self.action_button_missing_frames and
                isinstance(frame_sequence, int) and
                isinstance(previous_button_frame_sequence, int) and
                frame_sequence - previous_button_frame_sequence >= 2
            )
            current_opportunity = self._button_opportunity(
                buttons, self.hand_state.get("id"), button_context_street)
            current_opportunity["frameSequence"] = frame_sequence
            current_opportunity["capturedAt"] = frame_captured_at
            current_opportunity["pot"] = (float(pot_before_button)
                                          if isinstance(pot_before_button, (int, float)) else None)
            hero_invested = self.seat_trackers.get(hero_index, {}).get("stableBet")
            current_opportunity["heroInvested"] = (float(hero_invested)
                                                    if isinstance(hero_invested, (int, float)) else None)
            current_opportunity["latestConfirmedActionFrameSequence"] = max(
                (item.get("frameSequence") for item in self.action_log
                 if item.get("handId") == self.hand_state.get("id") and
                 item.get("street") == button_context_street and
                 isinstance(item.get("frameSequence"), int)),
                default=None,
            )
            current_opportunity["heroActionCount"] = sum(
                item.get("handId") == self.hand_state.get("id") and
                item.get("street") == button_context_street and
                item.get("seat") == hero_index + 1 and
                item.get("action") not in ("blind", "post_blind", "straddle")
                for item in self.action_log
            )
            same_opportunity_after_gap = bool(
                turn_confirmed and self.action_button_opportunity and
                (self._same_button_opportunity(self.action_button_opportunity,
                                               current_opportunity) or
                 self._same_unresolved_button_opportunity(
                     self.action_button_opportunity, current_opportunity))
            )
            preselection = self._update_hero_preselection(
                frame, turn_confirmed, frame_captured_at, frame_sequence,
                frame_video_second)
            if turn_confirmed and (not self.visual_turn_detected or turn_context_changed or
                                   button_reappeared_after_gap):
                self.visual_turn_detected = True
                self.visual_turn_hand_id = self.hand_state.get("id")
                self.visual_turn_street = button_context_street
                self.action_button_missing_frames = 0
                if not same_opportunity_after_gap:
                    self.action_button_sequence += 1
                self.action_button_opportunity = current_opportunity
                self.action_button_preselection = dict(preselection) if preselection else None
                if self.action_button_preselection:
                    self.action_button_preselection["actionButtonSequence"] = self.action_button_sequence
                self.action_button_detected_at = time.time()
                self.action_button_frame_captured_at = frame_captured_at
                self.action_button_frame_received_at = self.frame_received_at.get(
                    frame_sequence, frame_captured_at)
                self.action_button_frame_sequence = frame_sequence
                self.action_button_state_published_at = time.time()
                with self.state_lock:
                    self.cached_state = dict(self.cached_state or {})
                    self.cached_state["actionButtonSequence"] = self.action_button_sequence
                    self.cached_state["actionButtonDetectedAt"] = self.action_button_detected_at
                    self.cached_state["actionButtonFrameCapturedAt"] = frame_captured_at
                    self.cached_state["actionButtonFrameReceivedAt"] = self.action_button_frame_received_at
                    self.cached_state["actionButtonStatePublishedAt"] = self.action_button_state_published_at
            elif turn_confirmed:
                self.action_button_missing_frames = 0
                self.action_button_opportunity = current_opportunity
                current_actions = [item for item in self.action_log
                                   if item.get("handId") == self.hand_state.get("id") and
                                   item.get("street") == button_context_street]
                recovery_needed = (
                    self.formal_expected_seat == hero_index and
                    not any(item.get("action") in {
                        "call", "bet", "raise", "reraise", "allin", "fold", "check"
                    } for item in current_actions)
                )
                if recovery_needed and frame_sequence != self.action_button_frame_sequence:
                    self.action_button_frame_captured_at = frame_captured_at
                    self.action_button_frame_received_at = self.frame_received_at.get(
                        frame_sequence, frame_captured_at)
                    self.action_button_frame_sequence = frame_sequence
                    self.action_button_state_published_at = time.time()
            elif self.visual_turn_detected:
                self.action_button_missing_frames += 1
                if self.action_button_missing_frames >= 2:
                    self.visual_turn_detected = False
                    self.action_button_missing_frames = 0
        fast_stage_started_at = time.perf_counter()
        early_allin_event = None
        if turn_confirmed:
            defer_action_chain_probe = self.action_button_frame_sequence == frame_sequence
            chain_gap_seats = ([] if defer_action_chain_probe else
                               self._current_street_chain_gap_seats())
            for missing_seat in chain_gap_seats:
                fast_events.extend(self._capture_fast_actions_for_seat_context(
                    frame, self.hand_state.get("pot"), missing_seat, capture_context))
            prior_probe_seats = ([] if defer_action_chain_probe else
                                 self._prior_street_probe_seats())
            for missing_seat in prior_probe_seats:
                fast_events.extend(self._capture_fast_actions_for_seat_context(
                    frame, self.hand_state.get("pot"), missing_seat, capture_context))
            if self._probe_ocr_pending(prior_probe_seats):
                prior_deadline = time.monotonic() + .045
                while (self._probe_ocr_pending(prior_probe_seats) and
                       time.monotonic() < prior_deadline):
                    fast_events.extend(self._drain_action_ocr_results(
                        hero_buttons_visible=True,
                        hero_button_frame_sequence=frame_sequence))
                    time.sleep(.001)
                fast_events.extend(self._drain_action_ocr_results(
                    hero_buttons_visible=True,
                    hero_button_frame_sequence=frame_sequence))
            visible_probe_seats = self._hero_turn_probe_seats(hero_index)
            probe_seats = [] if defer_action_chain_probe else visible_probe_seats
            probe_seat = visible_probe_seats[0] if visible_probe_seats else None
            if any(button.get("kind") == "call" and
                   (button.get("value") == "allin" or button.get("allinCall"))
                   for button in buttons):
                early_seats = self._current_seat_snapshot()
                early_chips = self._decision_chips_from_ledger(early_seats)
                early_allin_event = self._confirm_unique_raise_from_hero_allin_call(
                    buttons, early_chips, hero_index, frame_captured_at,
                    frame_sequence, pot_after=self.hand_state.get("pot"))
                if early_allin_event is not None:
                    fast_events.append(early_allin_event)
                    probe_seats = self._hero_turn_probe_seats(hero_index)
                    probe_seat = probe_seats[0] if probe_seats else None
            if (not probe_seats and self.formal_expected_seat == hero_index and
                    any(button.get("kind") == "call" and
                        not isinstance(button.get("value"), (int, float)) and
                        button.get("value") != "allin"
                        for button in buttons)):
                buttons = self._recognize_visual_button_values(frame, buttons)
                turn_confirmed = self._official_action_cluster(buttons)
            probe_attempted = False
            probe_direct_event = False
            probe_started_at = None
            hero_turn_pot_after = self.hand_state.get("pot")
            hero_turn_pot_confidence = 0.0
            # A new hero-button appearance starts a new decision opportunity.
            # Include its sequence so an earlier probe cannot consume the
            # grace window for a later action on the same street.
            probe_key = (self.hand_state.get("id"), self.hand_state.get("street"),
                         tuple(visible_probe_seats), self.action_button_sequence)
            probe_frame_changed = getattr(self, "_hero_probe_frame_sequence", None) != frame_sequence
            if probe_seat is not None and getattr(self, "_hero_probe_key", None) == probe_key:
                if probe_frame_changed:
                    self._hero_probe_attempts = getattr(self, "_hero_probe_attempts", 0) + 1
            else:
                self._hero_probe_key = probe_key
                self._hero_probe_attempts = 1
                probe_frame_changed = True
            self._hero_probe_frame_sequence = frame_sequence
            if visible_probe_seats and probe_frame_changed:
                probe_attempted = True
                probe_started_at = time.monotonic()
                self._drain_center_ocr_results()
                current_center = self.center_ocr_cache.get(center_hash, {})
                if (self._unique_aggression_uses_pot_delta(buttons) and
                        (current_center.get("pot") is None or
                        float(current_center.get("confidence") or 0) < .65 or
                        current_center.get("pot") <= (pot_before_button or 0))):
                    line_pot, line_confidence = self._validated_button_frame_pot_line(
                        frame, frame_sequence)
                    if line_pot is not None:
                        current_center = {"pot": line_pot, "confidence": line_confidence}
                if (current_center.get("pot") is not None and
                        float(current_center.get("confidence") or 0) >= .65):
                    hero_turn_pot_after = current_center["pot"]
                    hero_turn_pot_confidence = float(current_center["confidence"])
                button_event = self._confirm_unique_aggression_from_hero_button(
                    buttons, hero_index, frame_captured_at, frame_sequence,
                    pot_before=pot_before_button,
                    pot_after=current_center.get("pot"),
                    pot_confidence=current_center.get("confidence", 0.0),
                )
                if button_event is not None:
                    fast_events.append(button_event)
                    probe_direct_event = True
                    visible_probe_seats = self._hero_turn_probe_seats(hero_index)
                    probe_seats = [] if defer_action_chain_probe else visible_probe_seats
                    probe_seat = visible_probe_seats[0] if visible_probe_seats else None
                if not probe_direct_event:
                    for missing_seat in probe_seats:
                        fast_events.extend(self._capture_fast_actions_for_seat_context(
                            frame, self.hand_state.get("pot"), missing_seat, capture_context))
                    fast_events.extend(self._drain_action_ocr_results(
                        hero_buttons_visible=True,
                        hero_button_frame_sequence=frame_sequence))
                    probe_direct_event = probe_seat is not None and any(
                        item.get("handId") == self.hand_state.get("id") and
                        item.get("street") == self.hand_state.get("street") and
                        item.get("seat") == probe_seat + 1 and
                        item.get("action") not in ("blind", "post_blind", "straddle") and
                        not item.get("inferred") and
                        (item.get("frameSequence") is None or
                         item.get("frameSequence") <= frame_sequence)
                        for item in self.action_log
                    )
                # A short-stack opponent can show an ALL IN badge in the
                # avatar/stack area on the same frame as the hero buttons.
                # Resolve that explicit evidence before applying any rule
                # fallback (a call-deficit fallback would otherwise fabricate
                # a fold and stop the action chain).
                if not probe_direct_event and probe_seat is not None:
                    explicit_allin = next((item for item in fast_events
                                           if item.get("handId") == self.hand_state.get("id") and
                                           item.get("street") == self.hand_state.get("street") and
                                           item.get("seat") == probe_seat + 1 and
                                           item.get("action") == "allin" and
                                           not item.get("inferred")), None)
                    if explicit_allin is not None:
                        probe_direct_event = True
                if probe_direct_event:
                    self._hero_probe_key = None
                    self._hero_probe_attempts = 0
                    self._hero_probe_frame_sequence = None
            terminal_events = self._confirm_probe_terminal_texts(
                frame, probe_seats, frame_captured_at, frame_sequence)
            if terminal_events:
                fast_events.extend(terminal_events)
                probe_seats = self._hero_turn_probe_seats(hero_index)
                probe_seat = probe_seats[0] if probe_seats else None
            probe_ocr_finished = not self._probe_ocr_pending(probe_seats)
            if (probe_seats and self.formal_expected_seat != hero_index and
                    self._next_opponent_seat(probe_seat) == hero_index):
                terminal_event = self._confirm_adjacent_terminal_text(
                    frame, probe_seats, hero_index, frame_captured_at, frame_sequence)
                if terminal_event is not None:
                    fast_events.append(terminal_event)
                    probe_ocr_finished = True
            for _ in range(len(TABLE_LAYOUTS[self.layout])):
                if self.formal_expected_seat in (None, hero_index):
                    break
                expected_tracker = self.seat_trackers.get(self.formal_expected_seat, {})
                allow_weak_inference = bool(
                    probe_attempted and probe_ocr_finished and
                    self._hero_probe_attempts >= 2 and
                    len(probe_seats) == 1 and
                    self._next_opponent_seat(probe_seat) == hero_index and
                    self.formal_expected_seat in probe_seats and
                    expected_tracker.get("visualState") != "allin"
                )
                prior_event = self._confirm_expected_actor_from_hero_turn(
                    hero_index, frame_captured_at, frame_sequence,
                    hero_turn_pot_after, require_immediate=False,
                    allow_weak_inference=allow_weak_inference,
                    hero_facing_call=any(button.get("kind") == "call" for button in buttons),
                )
                if prior_event is None:
                    break
                fast_events.append(prior_event)
        fast_events.extend(self._drain_action_ocr_results(
            hero_buttons_visible=turn_confirmed,
            hero_button_frame_sequence=frame_sequence))
        if turn_confirmed:
            self._promote_last_action_confirmed_by_hero_buttons(hero_index, frame_sequence)
        fast_stage_ms["heroProbe"] = round((time.perf_counter() - fast_stage_started_at) * 1000, 1)
        fast_stage_started_at = time.perf_counter()
        if (turn_confirmed and self.formal_expected_seat == hero_index and
                any(button.get("kind") == "call" and
                    not isinstance(button.get("value"), (int, float))
                    for button in buttons)):
            ledger_call = self._confirmed_ledger_call_amount(hero_index)
            if ledger_call is not None:
                buttons = [({**button, "value": ledger_call, "text": f"ledger:{ledger_call:g}",
                             "confidence": max(.9, float(button.get("confidence") or 0))}
                            if button.get("kind") == "call" and not button.get("allinCall")
                            else button) for button in buttons]
            else:
                buttons = self._recognize_visual_button_values(frame, buttons)
            turn_confirmed = self._official_action_cluster(buttons)
        if turn_confirmed and self.formal_expected_seat == hero_index:
            self._promote_allin_confirmed_by_equal_amounts(buttons, hero_index)
        fast_events.extend(self._drain_action_ocr_results(
            hero_buttons_visible=turn_confirmed,
            hero_button_frame_sequence=frame_sequence))
        seats = self._current_seat_snapshot()
        if turn_confirmed and self.decision_chip_recovery_sequence != self.action_button_sequence:
            self.decision_chip_recovery_sequence = self.action_button_sequence
            self.decision_chip_recovery_attempts = 0
        if (turn_confirmed and self.formal_expected_seat == hero_index and
                self.decision_chip_recovery_attempts < 3):
            current_actions = [item for item in self.action_log
                               if item.get("handId") == self.hand_state.get("id") and
                               item.get("street") == self.hand_state.get("street")]
            voluntary = {"call", "bet", "raise", "reraise", "allin", "fold", "check"}
            if not any(item.get("action") in voluntary for item in current_actions):
                self.decision_chip_recovery_attempts += 1
                for index in range(len(TABLE_LAYOUTS[self.layout])):
                    if index == hero_index:
                        continue
                    fast_events.extend(self._capture_fast_actions_for_seat_context(
                        frame, self.hand_state.get("pot"), index, capture_context))
                fast_events.extend(self._drain_action_ocr_results(
                    hero_buttons_visible=True,
                    hero_button_frame_sequence=frame_sequence))
                seats = self._current_seat_snapshot()
        decision_chips = self._decision_chips_from_ledger(seats) if turn_confirmed else {}
        if (turn_confirmed and not decision_chips and
                self._refresh_missing_decision_chips(
                    frame, seats, frame_captured_at, frame_sequence,
                    allow_integer=False)):
            decision_chips = self._decision_chips_from_ledger(seats)
        if turn_confirmed and not decision_chips:
            self.decision_chip_recovery_attempts += 1
            if self.decision_chip_recovery_attempts <= 3:
                self._refresh_missing_decision_chips(
                    frame, seats, frame_captured_at, frame_sequence,
                    allow_integer=True)
                decision_chips = self._decision_chips_from_ledger(seats)
        decision_chips, decision_chip_captured_at, decision_chip_frame_sequence = (
            self._bind_decision_chip_frame(
                decision_chips, frame_captured_at, frame_sequence)
            if turn_confirmed else ({}, None, None)
        )
        fast_stage_ms["seatSnapshot"] = round((time.perf_counter() - fast_stage_started_at) * 1000, 1)
        call_button = next((item for item in buttons if item["kind"] == "call"), None)
        hero_stack = decision_chips.get(str(hero_index), {})
        if (call_button and isinstance(call_button.get("value"), (int, float)) and
                isinstance(hero_stack.get("value"), (int, float)) and
                float(hero_stack.get("confidence") or 0) >= ACTION_STRATEGY_CONFIDENCE and
                call_button["value"] > hero_stack["value"] + .001):
            buttons = [({**button, "value": "allin", "allinCall": True,
                         "text": f"stack:{hero_stack['value']:g}",
                         "confidence": max(.9, float(button.get("confidence") or 0))}
                        if button is call_button else button) for button in buttons]
            call_button = next(item for item in buttons if item["kind"] == "call")
        allin_button, allin_call_amount = self._allin_call_evidence(
            buttons, decision_chips, hero_index)
        if turn_confirmed and allin_button:
            promoted_allin = self._promote_allin_confirmed_by_allin_call(buttons, hero_index)
            if promoted_allin is not None:
                seats = self._current_seat_snapshot()
                decision_chips = self._decision_chips_from_ledger(seats)
                decision_chips, decision_chip_captured_at, decision_chip_frame_sequence = (
                    self._bind_decision_chip_frame(
                        decision_chips, frame_captured_at, frame_sequence)
                )
        provisional_raise = None
        if turn_confirmed and allin_button:
            provisional_raise = self._confirm_unique_raise_from_hero_allin_call(
                buttons, decision_chips, hero_index, frame_captured_at, frame_sequence,
                pot_after=self.hand_state.get("pot"))
            if provisional_raise is not None:
                fast_events.append(provisional_raise)
                seats = self._current_seat_snapshot()
                decision_chips = self._decision_chips_from_ledger(seats)
                decision_chips, decision_chip_captured_at, decision_chip_frame_sequence = (
                    self._bind_decision_chip_frame(
                        decision_chips, frame_captured_at, frame_sequence)
                )
        if turn_confirmed and self.formal_expected_seat == hero_index and not allin_button:
            promoted_allin = self._promote_allin_confirmed_by_explicit_amount_and_hero_call(
                buttons, hero_index)
            fast_events.extend(self._drain_action_ocr_results(
                hero_buttons_visible=turn_confirmed,
                hero_button_frame_sequence=frame_sequence))
            seats = self._current_seat_snapshot()
            if promoted_allin is not None:
                decision_chips = self._decision_chips_from_ledger(seats)
                decision_chips, decision_chip_captured_at, decision_chip_frame_sequence = (
                    self._bind_decision_chip_frame(
                        decision_chips, frame_captured_at, frame_sequence)
                )
        center_result = self.center_ocr_cache.get(center_hash, {})
        pot = center_result.get("pot")
        pot_confidence = float(center_result.get("confidence") or 0)
        if turn_confirmed:
            line_pot, line_confidence = self._validated_button_frame_pot_line(
                frame, frame_sequence)
            if line_pot is not None and line_confidence >= .65:
                pot = line_pot
                pot_confidence = line_confidence
        if (turn_confirmed and pot is None and
                isinstance(hero_turn_pot_after, (int, float)) and
                hero_turn_pot_confidence >= .65):
            pot = hero_turn_pot_after
            pot_confidence = hero_turn_pot_confidence
        pending_allin_event = provisional_raise or early_allin_event
        if turn_confirmed and pending_allin_event is not None:
            pot, pot_confidence = self._reconcile_pending_allin_call_pot(
                pot, pot_confidence, pot_before_button, pending_allin_event)
        center_amounts = list(center_result.get("values") or [])
        center_fields = self._classify_center_amounts(center_amounts)
        call_amount = (allin_call_amount if allin_button else
                       call_button.get("value") if call_button else
                       0.0 if any(item["kind"] == "check" for item in buttons) else None)
        if turn_confirmed:
            self.fast_hero_buttons = list(buttons)
            self.fast_hero_buttons_second = getattr(self, "recording_second", None)
            self.fast_hero_no_button_frames = 0
            hero_prior_amount = max(
                (float(item.get("amount") or 0) for item in self.action_log
                 if item.get("handId") == self.hand_state.get("id") and
                 item.get("street") == button_context_street and
                 item.get("seat") == hero_index + 1),
                default=0.0,
            )
            existing_release = self.hero_button_release_context or {}
            release_chips_before = (hero_stack.get("value")
                                    if isinstance(hero_stack.get("value"), (int, float)) else None)
            if (existing_release.get("handId") == self.hand_state.get("id") and
                    existing_release.get("street") == button_context_street and
                    existing_release.get("actionButtonSequence") == self.action_button_sequence and
                    isinstance(existing_release.get("chipsBefore"), (int, float))):
                release_chips_before = existing_release["chipsBefore"]
            self.hero_button_release_context = {
                "handId": self.hand_state.get("id"),
                "street": button_context_street,
                "seat": hero_index + 1,
                "buttons": [dict(item) for item in buttons],
                "actionButtonSequence": self.action_button_sequence,
                "priorAmount": hero_prior_amount,
                "chipsBefore": release_chips_before,
                "lastVisibleFrameSequence": frame_sequence,
                "observedAt": frame_captured_at,
                "videoSecond": frame_video_second,
            }
        elif self.fast_hero_buttons:
            if (self.hand_started_second is not None and self.fast_hero_buttons_second is not None and
                    self.fast_hero_buttons_second < self.hand_started_second):
                self.fast_hero_buttons = []
                self.fast_hero_no_button_frames = 0
            else:
                self.fast_hero_no_button_frames += 1
            if self.fast_hero_buttons and self.fast_hero_no_button_frames >= 1:
                if self._hero_buttons_blocked_by_forced_bets():
                    self.fast_hero_buttons = []
                    self.fast_hero_no_button_frames = 0
                    return {"visualHeroTurn": False, "visualButtons": [], "heroTurn": False,
                            "buttons": [], "actionable": False,
                            "reactionEstimates": self._empty_reaction_estimates(),
                            "fastUpdatedAt": time.time()}
                hero_index = 4 if self.layout == "8max" else 3
                if not self.pending_hero_buttons:
                    self.pending_hero_buttons = list(self.fast_hero_buttons)
                    self.pending_hero_chips = (self.hero_button_release_context or {}).get("chipsBefore")
                    self.pending_hero_started = time.time()
                    self.pending_hero_second = self.fast_hero_buttons_second
                    self.pending_hero_frames = 0
                    self.pending_hero_hand_id = self.hand_state.get("id")
                    self.pending_hero_street = self.hand_state.get("street")
                possible = sorted({item.get("kind") for item in self.fast_hero_buttons
                                   if item.get("kind") in ("fold", "check", "call", "custom_raise")})
                resolved_action = "hero_action_unresolved"
                resolved_amount = None
                investment_box = self._seat_slot_box(hero_index, "investment", width, height)
                if investment_box:
                    ix1, iy1, ix2, iy2 = investment_box
                    crop = frame[max(0, iy1):min(height, iy2), max(0, ix1):min(width, ix2)]
                    if crop.size:
                        text, _ = self._ocr_line(cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC))
                        resolved_amount = self._extract_bet(text)
                call_button = next((item for item in self.fast_hero_buttons
                                    if item.get("kind") == "call" and isinstance(item.get("value"), (int, float))), None)
                release_context = self.hero_button_release_context or {}
                hero_tracker = self.seat_trackers.get(hero_index, {})
                prior_amount = float(release_context.get("priorAmount") or 0)
                resolved_amount = self._reconcile_hero_total_amount(
                    resolved_amount, prior_amount,
                    release_context.get("chipsBefore"), hero_tracker.get("chips"))
                if resolved_amount is not None and resolved_amount > 0:
                    resolved_action = ("call" if call_button and
                                       abs(resolved_amount - call_button["value"]) <= max(.05, call_button["value"] * .12)
                                       else "raise" if "custom_raise" in possible else "hero_action_unresolved")
                event = {"time": time.time(), "videoSecond": self.fast_hero_buttons_second,
                         "handId": self.hand_state.get("id", 0), "street": self.hand_state.get("street", "preflop"),
                         "sequence": 1, "seat": hero_index + 1,
                         "name": self.seat_trackers.get(hero_index, {}).get("name", "Zixia888"),
                         "action": resolved_action, "possibleActions": possible,
                         "avatarHash": self.seat_trackers.get(hero_index, {}).get("avatarHash", ""),
                         "amount": resolved_amount,
                         "increase": (max(0.0, resolved_amount - prior_amount)
                                      if isinstance(resolved_amount, (int, float)) else None),
                         "chipsBefore": release_context.get("chipsBefore"),
                         "chipsAfter": hero_tracker.get("chips"), "potAfter": pot,
                         "confidence": ACTION_STRATEGY_CONFIDENCE,
                         "evidence": "正式动作按钮消失且筹码未减少"}
                event["evidence"] = "official_buttons_disappeared+hero_investment_slot"
                event["actionButtonSequence"] = self.action_button_sequence
                event["buttonLastVisibleFrameSequence"] = self.hero_button_last_visible_frame_sequence
                event["buttonDisappearedFrameSequence"] = frame_sequence
                event["buttonDisappearedSecond"] = getattr(self, "recording_second", None)
                if resolved_action == "hero_action_unresolved":
                    self._append_action_candidate(event)
                else:
                    self._append_action_event(event)
                self.fast_hero_buttons = []
                self.fast_hero_no_button_frames = 0
        previous_pot = self.hand_state.get("pot")
        street_transition_pending = len(confirmed_board) in board_progression.get(len(previous_board), set())
        hand_is_visibly_reset = (
            len(previous_board) >= 3 and not board_cards
            and pot is not None and previous_pot is not None
            and pot < previous_pot * .55
        )
        if not hand_is_visibly_reset:
            fast_stage_started_at = time.perf_counter()
            fast_events.extend(self._drain_action_ocr_results(
                hero_buttons_visible=turn_confirmed,
                hero_button_frame_sequence=frame_sequence))
            seats = self._current_seat_snapshot()
            self._sync_fast_street(confirmed_board)
            fast_stage_ms["streetSync"] = round((time.perf_counter() - fast_stage_started_at) * 1000, 1)
        elif self.hand_state.get("street") == "preflop":
            confirmed_board = []
        if captured_hand_id != self.hand_state.get("id"):
            return None
        hero_cards = list(self.card_published.get("heroCards", []))
        valid_confirmed_board = (len(confirmed_board) in (0, 3, 4, 5) and
                                 len(set(confirmed_board)) == len(confirmed_board))
        with self.state_lock:
            cached_profiles = dict((self.cached_state or {}).get("opponentProfiles") or {})
            cached_history_status = dict((self.cached_state or {}).get("historyStatus") or {})
        if not cached_profiles:
            cached_profiles = self.history_store.summaries(seats)
            cached_history_status = self.history_store.status()
        active_player_count = sum(seat.get("occupancy") == "occupied" for seat in seats)
        expected_board_count = {"preflop": 0, "flop": 3, "turn": 4, "river": 5}.get(
            self.hand_state.get("street"))
        effective_pot, min_raise_to, preflop_full_raise_count = self._publish_fast_strategy_fields(
            pot, pot_confidence)
        fast_stage_started_at = time.perf_counter()
        reaction_estimates = (
            self._reaction_estimates_for_state(
                seats, effective_pot, call_amount, buttons, hero_index,
                min_raise_to=min_raise_to, allin_call=bool(allin_button)
            ) if turn_confirmed else self._empty_reaction_estimates()
        )
        fast_stage_ms["reaction"] = round((time.perf_counter() - fast_stage_started_at) * 1000, 1)
        dealer_reliable = bool(
            self.hand_dealer_index is not None and
            self.dealer_monitor_current == self.hand_dealer_index and
            self.dealer_monitor_candidate is None and
            not self.dealer_conflict
        )
        position_seats = self._current_hand_position_seats(seats)
        hero_position = (position_for(
            position_seats, hero_index, self.hand_dealer_index,
            self._straddle_seat_for_position(position_seats, self.hand_dealer_index))
                         if seats and self.hand_dealer_index is not None else "unknown")
        current_action_quality = all(
            not action.get("orderConflict") and action.get("strategyEligible", True)
            and float(action.get("confidence") or 0) >= ACTION_STRATEGY_CONFIDENCE
            for action in self.action_log
            if action.get("handId") == self.hand_state.get("id") and
            action.get("street") == self.hand_state.get("street")
        )
        recognition_inputs_reliable = bool(
            len(hero_cards) == 2 and
            visible_hero_cards == hero_cards and
            expected_board_count is not None and
            len(confirmed_board) == expected_board_count and
            visible_board_cards == confirmed_board and
            len(set(hero_cards + confirmed_board)) == len(hero_cards) + len(confirmed_board) and
            isinstance(effective_pot, (int, float)) and effective_pot > 0 and
            active_player_count >= 2 and dealer_reliable and
            hero_position != "unknown"
        )
        strategy_inputs_reliable = recognition_inputs_reliable and current_action_quality
        action_chain = self._action_chain_snapshot(
            self.hand_state.get("id"), self.hand_state.get("street"))
        chain_gap = next((item.get("missingSeats") or []
                          for item in action_chain.get("conflicts") or []
                          if item.get("missingSeats")), [])
        expected_action_seat = (chain_gap[0] if chain_gap else
                                action_chain["nextActorSeat"])
        expected_action_index = (None if expected_action_seat is None else
                                 int(expected_action_seat) - 1)
        action_chain_closed = (action_chain["reliable"] and
                               action_chain["nextActor"] == hero_index)
        field_context = {"handId": self.hand_state.get("id", 0),
                         "street": self.hand_state.get("street", "waiting"),
                         "frameSequence": frame_sequence, "observed_at": frame_captured_at,
                         "videoSecond": frame_video_second}
        self.fields.commit("heroCards", hero_cards, .98 if len(hero_cards) == 2 else .2,
                           "cards", len(hero_cards) == 2, **field_context)
        self.fields.commit("boardCards", confirmed_board, .92 if valid_confirmed_board else .2,
                           "fast_card_slots", valid_confirmed_board, **field_context)
        self.fields.commit("dealerIndex", self.hand_dealer_index, .98 if dealer_reliable else .2,
                           "dealer_fixed_slots", dealer_reliable, **field_context)
        self.fields.commit("heroPosition", hero_position, 1.0 if dealer_reliable else .2,
                           "dealer_rules", dealer_reliable and hero_position != "unknown", **field_context)
        self.fields.commit("callAmount", call_amount, .95 if call_button else .85 if call_amount == 0 else .1,
                           "official_buttons", call_amount is not None, **field_context)
        self.fields.commit("buttons", buttons, .96 if turn_confirmed else .2,
                           "official_buttons", turn_confirmed, **field_context)
        return {"runtimeId": self.runtime_id, "tableSession": self.table_session,
                "heroCards": hero_cards, "visibleHeroCards": visible_hero_cards,
                "boardCards": confirmed_board, "visibleBoardCards": visible_board_cards,
                "seats": seats, "activePlayerCount": active_player_count,
                "pot": effective_pot, "callAmount": call_amount if turn_confirmed else None,
                "minRaiseTo": min_raise_to,
                "preflopFullRaiseCount": preflop_full_raise_count,
                "buttons": buttons if turn_confirmed else [], "heroTurn": turn_confirmed,
                "visualButtons": buttons if turn_confirmed else [], "visualHeroTurn": turn_confirmed,
                "buttonRecognitionSource": button_recognition_source,
                "heroPreselection": self._matching_hero_preselection(),
                "actionButtonPreselection": (dict(self.action_button_preselection)
                                             if turn_confirmed and self.action_button_preselection else None),
                "dealerIndex": self.hand_dealer_index,
                "dealerSeat": None if self.hand_dealer_index is None else self.hand_dealer_index + 1,
                "handId": self.hand_state.get("id", 0),
                "dealerReliable": dealer_reliable,
                "heroPosition": hero_position,
                "street": self.hand_state.get("street", "waiting"),
                "expectedActionSeat": expected_action_seat,
                "heroActsAfterExpected": (expected_action_index is not None and
                                           self._next_tracker_seat(expected_action_index) == hero_index),
                "actionChain": action_chain,
                "actionLog": list(self.action_log), "actionCandidates": self.action_candidates[-30:],
                "unactedPlayers": self._unacted_count(seats),
                "opponentProfiles": cached_profiles,
                "historyStatus": cached_history_status,
                "peek": dict(self.peek_state),
                "reactionEstimates": reaction_estimates,
                "participating": self.participating_locked,
                "participationEvidence": dict(self.hero_evidence),
                "spectator": not self.participating_locked and len(hero_cards) != 2,
                "recognitionReliable": recognition_inputs_reliable,
                "actionQualityReliable": current_action_quality,
                "reliable": strategy_inputs_reliable,
                "actionable": strategy_inputs_reliable and turn_confirmed and action_chain_closed,
                "fastActionEvents": fast_events,
                "centerAmounts": center_amounts, "centerMoney": center_fields, "specialScene": None,
                "decisionDataFrameCapturedAt": frame_captured_at,
                "decisionDataFrameSequence": frame_sequence,
                "decisionDataFrameVideoSecond": frame_video_second,
                "decisionDataFrameReceivedAt": self.frame_received_at.get(
                    frame_sequence, frame_captured_at),
                "visualButtonFrameCapturedAt": frame_captured_at if turn_confirmed else None,
                "actionButtonDetectedAt": self.action_button_detected_at if turn_confirmed else None,
                "actionButtonFrameCapturedAt": self.action_button_frame_captured_at if turn_confirmed else None,
                "actionButtonFrameReceivedAt": self.action_button_frame_received_at if turn_confirmed else None,
                "actionButtonStatePublishedAt": getattr(self, "action_button_state_published_at", None) if turn_confirmed else None,
                "actionButtonSequence": self.action_button_sequence,
                "actionButtonHandId": self.hand_state.get("id", 0) if turn_confirmed else None,
                "actionButtonStreet": self.hand_state.get("street", "waiting") if turn_confirmed else None,
                "actionButtonFrameSequence": self.action_button_frame_sequence if turn_confirmed else None,
                "fastFrameCapturedAt": frame_captured_at,
                "fastFrameSequence": frame_sequence,
                "fastFrameVideoSecond": frame_video_second,
                "decisionBindingReliable": bool(turn_confirmed and frame_sequence is not None),
                "allinCall": bool(turn_confirmed and allin_button),
                "allinCallAmount": allin_call_amount if turn_confirmed else None,
                "decisionChipStacks": decision_chips,
                "decisionChipFrameCapturedAt": decision_chip_captured_at,
                "decisionChipFrameSequence": decision_chip_frame_sequence,
                "decisionChipHandId": self.hand_state.get("id", 0) if turn_confirmed else None,
                "decisionChipStreet": self.hand_state.get("street", "waiting") if turn_confirmed else None,
                "fastUpdatedAt": time.time(),
                "fastActionScanMs": round((actions_scanned_at - fast_state_started_at) * 1000, 1),
                "fastStageMs": fast_stage_ms,
                "fastTotalMs": round((time.time() - fast_state_started_at) * 1000, 1)}

    def _publish_fast_strategy_fields(self, pot, pot_confidence):
        pot_valid = (isinstance(pot, (int, float)) and pot >= 0 and
                     isinstance(pot_confidence, (int, float)) and pot_confidence >= .65)
        with self.action_state_lock:
            hand_id = self.hand_state.get("id", 0)
            street = self.hand_state.get("street", "preflop")
            self.fields.commit("pot", pot, pot_confidence, "fast", pot_valid,
                               handId=hand_id, street=street)
            if pot_valid:
                self.hand_state["pot"] = float(pot)
                if hasattr(self, "hand_machine"):
                    self.hand_machine.pot = float(pot)
            events = list(self.action_log)
        effective_pot = self.fields.value("pot", None, 1.5)
        big_blind = self.blind_amounts.get("big")
        min_raise_to = minimum_raise_to(events, hand_id, street, big_blind)
        preflop_full_raise_count = full_raise_count(events, hand_id, "preflop", big_blind)
        self.fields.commit("minRaiseTo", min_raise_to, 1.0, "rules", min_raise_to is not None)
        self.fields.commit("preflopFullRaiseCount", preflop_full_raise_count, 1.0, "rules",
                           preflop_full_raise_count is not None)
        return effective_pot, min_raise_to, preflop_full_raise_count

    @staticmethod
    def _empty_reaction_estimates():
        return {"modelVersion": 1, "candidates": {}, "reliable": False}

    def _reaction_estimates_for_state(self, seats, pot, call, buttons, hero_index,
                                      min_raise_to=None, allin_call=False):
        if (not isinstance(pot, (int, float)) or pot <= 0 or
                not isinstance(call, (int, float)) or allin_call):
            return self._empty_reaction_estimates()
        buttons = list(buttons or ())
        hero_stack = self._hero_stack_value(seats, hero_index)
        if not isinstance(hero_stack, (int, float)) or hero_stack <= 0:
            return self._empty_reaction_estimates()
        active = [dict(seat) for seat in seats if seat.get("occupancy") == "occupied" and
                  not seat.get("empty") and seat.get("index") != hero_index and
                  seat.get("action") != "fold"]
        if not active:
            return self._empty_reaction_estimates()
        effective_stack = max(
            (min(float(hero_stack), float(seat.get("chips"))) for seat in active
             if isinstance(seat.get("chips"), (int, float)) and seat.get("chips") >= 0),
            default=0.0,
        )
        if effective_stack <= 0:
            return self._empty_reaction_estimates()
        current_actions = [item for item in self.action_log
                           if item.get("handId") == self.hand_state.get("id") and
                           item.get("street") == self.hand_state.get("street")]
        hero_invested = max(
            (float(item["amount"]) for item in current_actions
             if item.get("seat") == hero_index + 1 and
             item.get("action") in ("blind", "post_blind", "straddle", "call",
                                    "bet", "raise", "reraise", "allin") and
             isinstance(item.get("amount"), (int, float))),
            default=0.0,
        )
        if isinstance(min_raise_to, (int, float)):
            min_raise_to = max(0.0, float(min_raise_to) - hero_invested)
        prior = [item.get("action") for item in current_actions if item.get("action")]
        board = list(self.card_published.get("boardCards", []))
        player_count = len(active) + 1
        responsive = [seat for seat in active if seat.get("action") != "allin"]
        if not responsive:
            return self._empty_reaction_estimates()
        active_indices = {seat.get("index") for seat in responsive}
        order = []
        seat_count = len(TABLE_LAYOUTS[self.layout])
        for offset in range(1, seat_count):
            candidate = (hero_index + offset) % seat_count
            if candidate in active_indices:
                order.append(candidate)
        dealer_index = getattr(self, "hand_dealer_index", None)
        position_seats = self._current_hand_position_seats(seats)
        straddle_index = self._straddle_seat_for_position(position_seats, dealer_index)
        hero_position = position_for(position_seats, hero_index, dealer_index, straddle_index)
        for seat in active:
            seat["position"] = position_for(
                position_seats, seat.get("index"), dealer_index, straddle_index
            )
        key = (self.hand_state.get("id"), self.hand_state.get("street"),
               tuple(board), round(float(pot), 4), round(float(call), 4),
               hero_position, round(effective_stack, 4),
               (round(float(min_raise_to), 4)
                if isinstance(min_raise_to, (int, float)) else None),
               tuple((item.get("kind"), item.get("value")) for item in buttons),
               tuple(order), tuple(prior[-8:]))
        if key == getattr(self, "reaction_estimate_cache_key", None):
            return getattr(self, "reaction_estimate_cache", self._empty_reaction_estimates())
        candidates = {}
        blind = self.blind_amounts.get("big")
        candidate_specs = []
        def platform_amount(value):
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value == 0:
                return value
            precision = 10 ** (1 - math.floor(math.log10(abs(value))))
            return round(value * precision) / precision
        for button in buttons:
            if button.get("kind") == "quick_bet" and isinstance(button.get("value"), (int, float)):
                ratio = float(button["value"])
                amount = min(float(effective_stack), platform_amount(
                    float(call) + (float(pot) + float(call)) * ratio))
                candidate_specs.append(("quick_bet", amount, ratio))
        has_custom_raise = any(button.get("kind") == "custom_raise" for button in buttons)
        if (has_custom_raise and isinstance(min_raise_to, (int, float)) and
                float(min_raise_to) > float(call) and float(min_raise_to) <= float(effective_stack)):
            candidate_specs.append(("minimum_raise", float(min_raise_to), None))
        if has_custom_raise:
            candidate_specs.append(("allin", float(effective_stack), None))
        seen = set()
        for kind, amount, ratio in candidate_specs:
            if not isinstance(amount, (int, float)) or amount <= float(call):
                continue
            amount = float(amount)
            identity = (kind, round(amount, 6))
            if identity in seen:
                continue
            seen.add(identity)
            context = {"street": self.hand_state.get("street", "unknown"),
                       "player_count": player_count, "position": "unknown",
                       "prior_actions": prior, "board": board,
                       "effective_stack": effective_stack, "big_blind": blind,
                       "bet_pot_ratio": (amount - call) / max(.000001, pot + call)}
            aggressor_action = (
                "bet" if self.hand_state.get("street") != "preflop" and float(call) <= 0
                else "raise"
            )
            estimate = self.history_store.estimate_ordered_reaction(
                responsive, order, context, aggressor_action, context["bet_pot_ratio"],
                include_paths=True)
            estimate = dict(estimate or {})
            estimate.update(kind=kind, ratio=ratio, amount=amount,
                             sampleCount=estimate.get("minPersonalSamples", 0),
                             populationSampleCount=estimate.get("minPopulationSamples", 0))
            candidates[f"{kind}:{amount:g}"] = estimate
            if kind == "quick_bet" and ratio is not None:
                candidates[f"quick_bet:{ratio:g}"] = estimate
        result = {"modelVersion": 1, "candidates": candidates,
                  "updatedAt": time.time(), "reliable": bool(candidates) and
                  all(item.get("reliable") for item in candidates.values())}
        self.reaction_estimate_cache_key = key
        self.reaction_estimate_cache = result
        return result

    def _current_hand_position_seats(self, seats):
        eligible = set(self._current_hand_eligible_indices())
        dealer = getattr(self, "hand_dealer_index", None)
        if len(eligible) < 2 or dealer is not None and dealer not in eligible:
            return seats
        return [dict(seat, occupancy=("occupied" if seat.get("index") in eligible else "empty"))
                for seat in seats]

    @staticmethod
    def _hero_stack_value(seats, hero_index):
        seat = next((item for item in seats if item.get("index") == hero_index), None)
        return seat.get("chips") if seat else None

    def _current_seat_snapshot(self):
        with self.action_state_lock:
            with self.state_lock:
                cached = {seat.get("index"): dict(seat)
                          for seat in (self.cached_state or {}).get("seats", [])}
            hero_index = 4 if self.layout == "8max" else 3
            current_hand = self.hand_state.get("id")
            folded = {item.get("seat") for item in self.action_log
                      if item.get("handId") == current_hand and item.get("action") == "fold"}
            result = []
            for index in range(len(TABLE_LAYOUTS[self.layout])):
                tracker = self.seat_trackers.get(index, {})
                seat = cached.get(index, {"index": index})
                action = "fold" if index + 1 in folded else tracker.get("lastAction", "waiting")
                tracker_occupancy = tracker.get("occupancy")
                cached_occupancy = seat.get("occupancy")
                occupancy = (tracker_occupancy if tracker_occupancy in ("occupied", "empty")
                             else cached_occupancy if cached_occupancy in ("occupied", "empty")
                             else "unknown")
                seat.update({
                    "index": index,
                    "name": tracker.get("name") or seat.get("name", ""),
                    "chips": (tracker.get("chips") if tracker.get("chips") is not None
                              else seat.get("chips")),
                    "chipConfidence": max(float(tracker.get("chipConfidence") or 0),
                                          float(seat.get("chipConfidence") or 0)),
                    "avatarHash": tracker.get("avatarHash") or seat.get("avatarHash", ""),
                    "occupancy": occupancy,
                    "empty": occupancy != "occupied",
                    "action": action,
                    "streetBet": float(tracker.get("stableBet") or 0),
                    "isHero": index == hero_index,
                })
                if tracker.get("observedAt") is not None:
                    seat["observedAt"] = tracker["observedAt"]
                if tracker.get("frameSequence") is not None:
                    seat["frameSequence"] = tracker["frameSequence"]
                if tracker.get("videoSecond") is not None:
                    seat["videoSecond"] = tracker["videoSecond"]
                result.append(seat)
            if len(result) == len(TABLE_LAYOUTS[self.layout]):
                self.fast_seat_snapshot = [dict(seat) for seat in result]
                self.fast_seat_snapshot_at = time.time()
        return result

    @staticmethod
    def _official_action_cluster(buttons):
        kinds = {button.get("kind") for button in buttons}
        fold = next((button for button in buttons if button.get("kind") == "fold" and
                     button.get("color") == "red" and button.get("y", 0) >= .72 and
                     button.get("x", 1) <= .48), None)
        check = next((button for button in buttons if button.get("kind") == "check" and
                      button.get("color") in ("blue", "green", "gray") and
                      button.get("y", 0) >= .70 and button.get("x", 0) > .58), None)
        custom_raise = next((button for button in buttons if button.get("kind") == "custom_raise" and
                             button.get("color") == "blue" and button.get("y", 0) >= .72 and
                             .40 <= button.get("x", 0) <= .65), None)
        return bool((fold and ("call" in kinds or "check" in kinds)) or
                    (not fold and check and custom_raise))

    @staticmethod
    def _allin_call_evidence(buttons, decision_chips, hero_index):
        button = next((item for item in buttons
                       if item.get("kind") == "call" and
                       (item.get("value") == "allin" or item.get("allinCall"))), None)
        stack = (decision_chips or {}).get(str(hero_index), {})
        amount = (stack.get("value") if button and
                  isinstance(stack.get("value"), (int, float)) and
                  float(stack.get("confidence") or 0) >= ACTION_STRATEGY_CONFIDENCE else None)
        return button, amount

    def _decision_chips_from_ledger(self, seats=None):
        if seats is None:
            cached = self.cached_state or {}
            seats = list(cached.get("seats", []))
        else:
            seats = list(seats)
        folded = {item.get("seat") for item in self.action_log
                  if item.get("handId") == self.hand_state.get("id") and item.get("action") == "fold"}
        hero_index = 4 if self.layout == "8max" else 3
        eligible = self._current_hand_eligible_indices()
        hand_id = self.hand_state.get("id")
        history_by_hand = getattr(self, "hand_chip_history", None)
        if history_by_hand is None:
            self.hand_chip_history = history_by_hand = {}
        history = history_by_hand.setdefault(hand_id, {})
        required = [index for index in range(len(TABLE_LAYOUTS[self.layout]))
                    if index + 1 not in folded and
                    (index == hero_index or index in eligible) and
                    (index >= len(seats) or not seats[index].get("empty"))]
        result = {}
        for index in required:
            if index >= len(seats):
                return {}
            seat = seats[index]
            chips = seat.get("chips")
            observed_at = seat.get("observedAt")
            if not isinstance(chips, (int, float)):
                return {}
            confidence = float(seat.get("chipConfidence") or 0)
            used_history = False
            if confidence >= ACTION_STRATEGY_CONFIDENCE:
                history[index] = {
                    "chips": float(chips), "confidence": confidence,
                    "observedAt": observed_at,
                }
            elif index in history:
                trusted = history[index]
                chips = trusted["chips"]
                confidence = trusted["confidence"]
                observed_at = trusted["observedAt"]
                used_history = True
            later = [item for item in self.action_log
                     if item.get("handId") == self.hand_state.get("id") and
                     item.get("seat") == index + 1 and
                     float(item.get("observedAt") or 0) > observed_at and
                     item.get("action") in ("blind", "post_blind", "straddle", "call", "bet",
                                             "raise", "reraise", "allin")]
            increases = []
            for item in later:
                increase = item.get("increase")
                if not isinstance(increase, (int, float)) and isinstance(item.get("amount"), (int, float)):
                    prior = max(
                        (float(previous.get("amount") or 0) for previous in self.action_log
                         if previous is not item and previous.get("handId") == item.get("handId") and
                         previous.get("street") == item.get("street") and
                         previous.get("seat") == item.get("seat") and
                         previous.get("action") in ("blind", "post_blind", "straddle", "call", "bet",
                                                    "raise", "reraise", "allin") and
                         float(previous.get("observedAt") or 0) < float(item.get("observedAt") or 0)),
                        default=0.0,
                    )
                    increase = max(0.0, float(item["amount"]) - prior)
                if not isinstance(increase, (int, float)):
                    return {}
                increases.append(float(increase))
            value = (round(max(0.0, float(chips) - sum(increases)), 6)
                     if later else round(float(chips), 6))
            ledger_evidence_reliable = bool(later and all(
                not item.get("orderConflict") and item.get("strategyEligible", True) and
                float(item.get("confidence") or 0) >= .80
                for item in later
            ))
            result[str(index)] = {"value": value, "confidence": min(
                confidence,
                min((float(item.get("confidence") or 0) for item in later), default=1.0)),
                "source": ("confirmed_stack_plus_action_ledger" if later else
                           "confirmed_stack_history" if used_history else
                           "same_frame_seat_stack_fallback"),
                "ledgerEvidenceReliable": ledger_evidence_reliable}
        return result

    def _bind_decision_chip_frame(self, decision_chips, captured_at, frame_sequence):
        actions = tuple(
            (item.get("seat"), item.get("action"), item.get("amount"),
             item.get("increase"), item.get("frameSequence"))
            for item in self.action_log
            if item.get("handId") == self.hand_state.get("id") and
            item.get("street") == self.hand_state.get("street")
        )
        key = (self.hand_state.get("id"), self.hand_state.get("street"),
               self.action_button_sequence, actions)
        if decision_chips:
            self.decision_chip_frame_cache = {
                "key": key, "stacks": {seat: dict(value) for seat, value in decision_chips.items()},
                "capturedAt": captured_at, "frameSequence": frame_sequence,
            }
            return decision_chips, captured_at, frame_sequence
        cached = getattr(self, "decision_chip_frame_cache", None) or {}
        age = float(captured_at) - float(cached.get("capturedAt") or 0)
        if cached.get("key") == key and 0 <= age <= .08:
            return ({seat: dict(value) for seat, value in cached["stacks"].items()},
                    cached["capturedAt"], cached["frameSequence"])
        return {}, captured_at, frame_sequence

    def _refresh_missing_decision_chips(self, frame, seats, captured_at, frame_sequence,
                                        allow_integer=False):
        folded = {item.get("seat") for item in self.action_log
                  if item.get("handId") == self.hand_state.get("id") and
                  item.get("action") == "fold"}
        hero_index = 4 if self.layout == "8max" else 3
        eligible = self._current_hand_eligible_indices()
        required = [index for index in range(len(TABLE_LAYOUTS[self.layout]))
                    if index + 1 not in folded and
                    (index == hero_index or index in eligible) and
                    index < len(seats) and not seats[index].get("empty")]
        refreshed = False
        for index in required:
            seat = seats[index]
            if (isinstance(seat.get("chips"), (int, float)) and
                    float(seat.get("chipConfidence") or 0) >= ACTION_STRATEGY_CONFIDENCE):
                continue
            items = self._decision_chip_ocr_items(frame, index)
            item = next((candidate for candidate in reversed(items)
                         if self._extract_number(candidate.get("text", "")) is not None and
                         (allow_integer or "." in str(candidate.get("text") or "")) and
                         (not allow_integer or self._extract_number(candidate.get("text", "")) >= 1) and
                         float(candidate.get("confidence") or 0) >= ACTION_STRATEGY_CONFIDENCE), None)
            if item is None:
                continue
            value = self._extract_number(item["text"])
            confidence = float(item["confidence"])
            seat.update(chips=value, chipConfidence=confidence,
                        observedAt=captured_at, frameSequence=frame_sequence)
            tracker = self.seat_trackers.get(index)
            if tracker is not None:
                tracker.update(chips=value, chipConfidence=confidence,
                               observedAt=captured_at, frameSequence=frame_sequence)
            refreshed = True
        return refreshed

    def _decision_chip_ocr_items(self, frame, index):
        height, width = frame.shape[:2]
        box = self._seat_slot_box(index, "chips", width, height)
        if not box:
            return []
        x1, y1, x2, y2 = box
        y1 += round((y2 - y1) * .42)
        crop = frame[max(0, y1):min(height, y2), max(0, x1):min(width, x2)]
        if crop.size == 0:
            return []
        text, confidence = self._decision_chip_ocr_line(cv2.resize(
            crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC))
        if text and confidence < .9:
            gray = cv2.normalize(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), None, 0, 255,
                                 cv2.NORM_MINMAX)
            retry_text, retry_confidence = self._decision_chip_ocr_line(cv2.resize(
                gray, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC))
            if (self._extract_number(retry_text) == self._extract_number(text) and
                    retry_confidence > confidence):
                text, confidence = retry_text, retry_confidence
        return ([{"kind": "chips", "text": text, "confidence": confidence}]
                if text else [])

    def _start_startup_chip_scan(self, frame, captured_at, frame_sequence):
        if self.startup_chip_scan_running or self.startup_chip_scan_complete:
            return False
        self.startup_chip_scan_running = True

        def scan():
            try:
                for index in range(len(TABLE_LAYOUTS[self.layout])):
                    if self._hero_turn_latched():
                        break
                    item = next((candidate for candidate in self._decision_chip_ocr_items(
                        frame, index) if self._extract_number(candidate.get("text", "")) is not None and
                        "." in str(candidate.get("text") or "") and
                        float(candidate.get("confidence") or 0) >= ACTION_STRATEGY_CONFIDENCE), None)
                    if item is None:
                        continue
                    value = self._extract_number(item["text"])
                    confidence = float(item["confidence"])
                    tracker = self.seat_trackers.setdefault(index, {
                        "occupancy": "unknown", "pendingOccupancy": None, "occupancyFrames": 0,
                        "name": "", "chips": None, "avatar": "", "avatarHash": "",
                        "stableBet": 0.0, "pendingBet": None, "betFrames": 0,
                        "active": False, "lastAction": "waiting", "lastEvidence": "none",
                    })
                    tracker.update(chips=value, chipConfidence=confidence,
                                   observedAt=captured_at, frameSequence=frame_sequence,
                                   videoSecond=getattr(self, "recording_second", None))
                    self._set_seat_occupancy(index, "occupied", "startup_chip_scan",
                                             captured_at, getattr(self, "recording_second", None))
            finally:
                self.startup_chip_scan_running = False
                self.startup_chip_scan_complete = True
                self.slow_refresh_event.set()

        threading.Thread(target=scan, daemon=True).start()
        return True

    def _capture_slow_state_legacy(self):
        with self.capture_lock:
            frame = self.latest_table_frame.copy() if self.latest_table_frame is not None else None
            capture_bbox = list(self.latest_capture_bbox) if self.latest_capture_bbox else None
            seat_frame_captured_at = self.latest_frame_captured_at
            seat_frame_sequence = self.latest_frame_sequence
        seat_hand_id = self.hand_state.get("id", 0)
        seat_street = self.hand_state.get("street", "waiting")
        if frame is None:
            return {"status": "正在自动寻找绿色牌桌", "seats": [], "reliable": False, "spectator": True}
        special_scene = self._detect_special_scene(frame)
        if special_scene:
            label = "保险选择中" if special_scene == "insurance" else "全下发牌动画中"
            return {"status": f"v{APP_VERSION} · {label}", "specialScene": special_scene,
                    "visualHeroTurn": False, "visualButtons": [], "buttons": [], "heroTurn": False,
                    "actionable": False, "slowUpdatedAt": time.time()}
        started = time.time()
        height, width = frame.shape[:2]
        self._update_layout(self._detect_layout(frame))
        blind_box = self._reviewed_slot_box((210, 1060, 690, 1150), width, height)
        blind_crop = frame[blind_box[1]:blind_box[3], blind_box[0]:blind_box[2]]
        blind_items = self._ocr_items(blind_crop)
        slot_parsed_blinds = next((parsed for item in blind_items
                                   if (parsed := parse_blind_text(item.get("text"))) is not None), None)
        if parsed_blinds is not None:
            candidate = (parsed_blinds["small"], parsed_blinds["big"])
            if candidate == self.blind_text_candidate:
                self.blind_text_frames += 1
            else:
                self.blind_text_candidate = candidate
                self.blind_text_frames = 1
            if self.blind_text_frames >= 2 or self.blind_amounts.get("big") in (None, 0):
                self.blind_amounts.update(small=candidate[0], big=candidate[1])
                self.blind_straddle = parsed_blinds.get("straddle")
                self.blind_currency = parsed_blinds.get("currency", "usd")
                self.blind_text_raw = parsed_blinds["raw"]
                self.blind_ante = parsed_blinds.get("ante") if parsed_blinds.get("hasAnte") else 0.0
                rake_players = max(2, sum(1 for tracker in self.seat_trackers.values()
                                          if tracker.get("occupancy") == "occupied"))
                rake = lookup_rake(candidate[0], candidate[1], parsed_blinds.get("ante"), rake_players,
                                    parsed_blinds.get("straddle"), self.blind_currency, self.table_play)
                self.rake_rate = rake["rate"] if rake else None
                self.rake_cap = rake["cap"] if rake else None
                self.rake_players = rake_players if rake else None
                self.rake_source = "blind_table" if rake else None
        table_info_box = self._reviewed_slot_box((250, 1015, 650, 1100), width, height)
        table_info_crop = frame[table_info_box[1]:table_info_box[3], table_info_box[0]:table_info_box[2]]
        enlarged = cv2.resize(table_info_crop, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(enlarged, cv2.COLOR_BGR2GRAY)
        enhanced = cv2.convertScaleAbs(gray, alpha=1.8, beta=15)
        variants = (enlarged, enhanced, cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1])
        candidates = []
        for variant in variants:
            items = self._ocr_items(variant)
            text = " ".join(str(item.get("text", "")) for item in items).strip()
            if text:
                candidates.append(text)
            if parse_table_play(text) and parse_table_number(text):
                break
        table_info_text = max(candidates, key=lambda text: (bool(parse_table_play(text)),
                              bool(parse_table_number(text)), len(text)), default="")
        self.table_identity_ocr = table_info_text
        self.fields.commit("tableIdentityOcr", table_info_text, 1.0 if table_info_text else 0.0,
                           "reviewed_table_info_slot", bool(table_info_text))
        parsed_play = parse_table_play(table_info_text)
        if parsed_play is not None:
            self.table_play = parsed_play
        parsed_number = parse_table_number(table_info_text)
        self._observe_table_number(parsed_number)
        with self.state_lock:
            self.cached_state = dict(self.cached_state or {})
            self.cached_state.update({
                "tablePlay": self.table_play,
                "tableNumber": self.table_number,
                "tableIdentityOcr": self.table_identity_ocr,
                "blindTextRaw": self.blind_text_raw,
                "blindSmall": self.blind_amounts.get("small"),
                "blindBig": self.blind_amounts.get("big"),
                "blindStraddle": self.blind_straddle,
                "blindAnte": self.blind_ante,
                "rakeRate": self.rake_rate,
                "rakeCap": self.rake_cap,
                "rakePlayers": self.rake_players,
                "rakeSource": self.rake_source,
            })
        identity_state = self._capture_slow_identity_state(
            frame, seat_frame_captured_at, seat_frame_sequence, started)
        identity_state.update({
            "status": f"v{APP_VERSION} · 慢通道仅更新身份与牌桌信息",
            "layout": self.layout,
            "tablePlay": self.table_play,
            "tableNumber": self.table_number,
            "tableIdentityOcr": self.table_identity_ocr,
            "blindTextRaw": self.blind_text_raw,
            "blindSmall": self.blind_amounts.get("small"),
            "blindBig": self.blind_amounts.get("big"),
            "blindStraddle": self.blind_straddle,
            "blindAnte": self.blind_ante,
            "rakeRate": self.rake_rate,
            "rakeCap": self.rake_cap,
            "specialScene": None,
            "spectator": not self.participating_locked,
            "reliable": False,
        })
        return identity_state
        table_ocr = self._ocr_items(frame)
        seat_ocr = {index: table_ocr for index in range(len(TABLE_LAYOUTS[self.layout]))}
        seats = [self._read_seat(frame, index, center, seat_ocr.get(index, []))
                 for index, center in enumerate(TABLE_LAYOUTS[self.layout])]
        for seat in seats:
            seat["observedAt"] = (seat_frame_captured_at
                                  if seat_frame_captured_at is not None else started)
            seat["frameSequence"] = seat_frame_sequence
            seat["videoSecond"] = getattr(self, "recording_second", None)
        pot = self.fields.value("pot", self.hand_state.get("pot"), 5.0)
        board_band = frame[int(height * .38):int(height * .62), int(width * .18):int(width * .82)]
        observed_board_cards = list(self.card_published.get("boardCards", []))
        observed_hero_cards = list(self.card_published.get("heroCards", []))
        board_cards = list(self.card_published.get("boardCards", []))
        hero_cards = list(self.card_published.get("heroCards", []))
        self.hero_cards_present = len(observed_hero_cards) == 2
        buttons = list((self.cached_state or {}).get("visualButtons", []))
        hero_index = 4 if self.layout == "8max" else 3
        dealer_index = self.hand_dealer_index
        if dealer_index is None:
            dealer_index = self.fast_dealer_candidate if self.fast_dealer_frames >= 2 else self._detect_dealer_index(frame, table_ocr)
        expected_dealer = self._next_occupied_seat(seats, self.hand_dealer_index)
        if self.hand_dealer_index is not None and dealer_index not in (self.hand_dealer_index, expected_dealer):
            dealer_index = self.hand_dealer_index
        hero_position = self._hero_position(hero_index, dealer_index, active_player_count if 'active_player_count' in locals() else len(seats))
        hero = seats[hero_index]
        hero["isHero"] = True
        expected_small_blind = self._next_occupied_seat(seats, dealer_index)
        expected_big_blind = self._next_occupied_seat(seats, expected_small_blind)
        hero_forced_amount = float(hero.get("streetBet") or 0)
        if (self.hand_state.get("street") == "preflop" and hero_index == expected_big_blind and
                hero_forced_amount > 0 and getattr(self, "waiting_for_forced_bets", False)):
            hero["action"] = "blind"
        hero_stack_items = self._items_in_box(table_ocr, width * .34, height * .90, width * .66, height * .995)
        hero_stack_values = [(self._extract_number(item["text"]), float(item["confidence"]))
                             for item in hero_stack_items]
        hero_stack_values = [item for item in hero_stack_values if item[0] is not None]
        if hero_stack_values:
            hero["chips"], hero["chipConfidence"] = hero_stack_values[-1]
        hero_cards_present = bool(self.hero_cards_present)
        hero["occupied"] = not hero.get("empty") and bool(hero.get("name") or hero.get("chips") or hero_cards_present)
        hero["identityConfidence"] = hero["confidence"]
        hero["cards"] = hero_cards
        hero["emptyConfirmed"] = not hero["occupied"] and hero["confidence"] >= .75
        strategy_inputs_reliable = (
            len(hero_cards) == 2
            and pot is not None
            and pot > 0
            and (not board_cards or len(board_cards) in (3, 4, 5))
        )
        street_visual_changed = len(observed_board_cards) != len(self.hand_state.get("boardCards", []))
        if street_visual_changed:
            self.pending_hero_buttons = []
            self.previous_buttons = []
        hero_action = None if street_visual_changed else self._infer_hero_action(hero, buttons)
        call_button = next((button for button in buttons if button["kind"] == "call" and isinstance(button.get("value"), (int, float))), None)
        call_amount = call_button["value"] if call_button else 0.0 if any(button["kind"] == "check" for button in buttons) else None
        lower_items = [item for item in table_ocr if item["cy"] >= height * .62]
        lower_text = re.sub(r"[^a-z0-9]", "", "".join(item["text"] for item in lower_items).lower())
        hero_name = re.sub(r"[^a-z0-9]", "", (hero.get("name") or "").lower())
        hero_avatar_match = self._hero_avatar_match(frame, hero_index)
        dedicated_name = hero.get("name", "")
        name_evidence = "zixia888" in lower_text or hero_name == "zixia888" or "zixia888" in re.sub(r"[^a-z0-9]", "", dedicated_name.lower())
        if "zixia888" in re.sub(r"[^a-z0-9]", "", dedicated_name.lower()):
            hero["name"] = "Zixia888"
            tracker = self.seat_trackers.get(hero_index)
            if tracker:
                tracker["name"] = "Zixia888"
        if (self.participating_locked or hero_cards_present) and hero.get("action") not in (
                "blind", "post_blind", "straddle"):
            hero["action"] = "waiting"
        participation_evidence = hero_cards_present or name_evidence or hero_avatar_match
        self.hero_evidence = {"name": name_evidence, "avatar": hero_avatar_match, "cards": hero_cards_present,
                              "cardsReliable": len(hero_cards) == 2, "nameText": dedicated_name}
        if participation_evidence:
            self.participating_locked = True
            self.leave_evidence_frames = 0
        elif hero.get("emptyConfirmed"):
            self.leave_evidence_frames += 1
            if self.leave_evidence_frames >= 5:
                self.participating_locked = False
                self.hand_active = False
                self.current_hand = {}
        else:
            self.leave_evidence_frames = 0
        participating = self.participating_locked
        spectator = not participating
        seats = self._update_table_state(seats, hero_index, participating, hero_has_cards=hero_cards_present)
        seats[hero_index]["isHero"] = True
        hand = self._update_hand_state(seats, hero_cards, board_cards, pot, participating, dealer_index)
        self.fast_dealer_changed = False
        observed_forced_bets = {seat["index"]: float(seat.get("streetBet") or 0) for seat in seats}
        observed_forced_actions = {seat["index"]: seat.get("action") for seat in seats}
        for seat in seats:
            if seat.get("action") in ("fold", "check", "call", "bet", "raise", "reraise", "allin"):
                seat["action"] = "waiting"
        seats, events = self._update_action_state(seats, reset=hand["newHand"], pot_after=pot)
        if hand["newHand"]:
            forced = []
            small_blind = self._next_occupied_seat(seats, self.hand_dealer_index)
            big_blind = self._next_occupied_seat(seats, small_blind)
            straddle_seat = (self._next_occupied_seat(seats, big_blind)
                             if self._straddle_allowed_for_hand(seats) else None)
            same_frame_small = observed_forced_bets.get(small_blind, 0.0) if small_blind is not None else 0.0
            same_frame_big = observed_forced_bets.get(big_blind, 0.0) if big_blind is not None else 0.0
            if same_frame_big > 0 and same_frame_small > same_frame_big * 5:
                prior_small = float(self.blind_amounts.get("small") or 0)
                same_frame_small = prior_small if 0 < prior_small < same_frame_big else same_frame_big / 2
                observed_forced_bets[small_blind] = same_frame_small
            for seat in seats:
                amount = observed_forced_bets.get(seat["index"], 0.0)
                direct = observed_forced_actions.get(seat["index"])
                kind = "blind" if seat["index"] in (small_blind, big_blind) and amount > 0 else direct if direct in ("post_blind", "straddle") and amount > 0 else None
                if not kind:
                    continue
                event = {"time": time.time(), "handId": hand["id"], "street": "preflop", "sequence": 0,
                         "seat": seat["index"] + 1, "name": seat.get("name", ""), "action": kind,
                         "avatarHash": seat.get("avatarHash", ""), "amount": amount, "increase": amount,
                         "chipsAfter": seat.get("chips"), "potAfter": pot, "confidence": .9,
                         "evidence": "新手强制下注位置与金额"}
                if self._append_action_event(event):
                    forced.append(event)
                if kind == "blind":
                    if seat["index"] == small_blind:
                        self.blind_amounts["small"] = amount
                    elif seat["index"] == big_blind:
                        self.blind_amounts["big"] = amount
            configured_straddle = self._append_configured_forced_straddle(
                "牌桌盲注规则+庄家位置确认松浪盲注",
                observed_at=getattr(self, "latest_frame_captured_at", None), pot_after=pot)
            if configured_straddle is not None:
                forced.append(configured_straddle)
            events = forced + events
            if (dealer_index is not None and
                    sum(item.get("action") == "blind" for item in forced) >= 2):
                self.hand_boundary_confirmed = True
            for seat in seats:
                amount = observed_forced_bets.get(seat["index"], 0.0)
                direct = observed_forced_actions.get(seat["index"])
                big_blind_amount = self.blind_amounts.get("big") or 0
                same_frame_big = observed_forced_bets.get(big_blind, 0.0) if big_blind is not None else 0.0
                if (seat["index"] == straddle_seat and same_frame_big > 0 and
                        amount >= same_frame_big * 1.9 and direct not in ("post_blind", "straddle")):
                    direct = "straddle"
                if (seat["index"] not in (small_blind, big_blind) and same_frame_big > 0 and
                        abs(amount - same_frame_big) <= .01):
                    direct = "post_blind"
                if direct not in ("post_blind", "straddle", "bet", "call", "raise") and amount > big_blind_amount + .01:
                    direct = "raise"
                if direct not in ("post_blind", "straddle", "bet", "call", "raise") or amount <= 0:
                    continue
                event = {"time": time.time(), "videoSecond": getattr(self, "recording_second", None),
                         "handId": hand["id"], "street": "preflop", "sequence": 1,
                         "seat": seat["index"] + 1, "name": seat.get("name", ""), "action": direct,
                         "avatarHash": seat.get("avatarHash", ""), "amount": amount, "increase": amount,
                         "chipsAfter": seat.get("chips"), "potAfter": pot, "confidence": .88,
                         "evidence": "新手初始画面已存在明确动作文字和金额"}
                if self._append_action_event(event):
                    events.append(event)
        if hero_action and not self.hand_closed:
            hero_event = {
                "time": hero_action.get("observedAt", time.time()), "handId": hand["id"], "street": hand["street"],
                "videoSecond": hero_action.get("observedSecond"),
                "sequence": 1 + sum(item.get("street") == hand["street"] and item.get("action") != "blind"
                                    for item in self.action_log),
                "seat": hero_index + 1, "name": hero.get("name", ""),
                "action": hero_action["action"], "avatarHash": hero.get("avatarHash", ""),
                "amount": hero_action.get("totalAmount", float(hero.get("streetBet") or 0)),
                "increase": hero_action.get("amount", 0),
                "chipsBefore": hero_action.get("chipsBefore"),
                "chipsAfter": hero.get("chips"), "potAfter": pot,
                "confidence": hero_action.get("confidence", .65), "evidence": "正式动作按钮消失及投入变化",
            }
            if self._append_action_event(hero_event):
                events.append(hero_event)
                tracker = self.seat_trackers.get(hero_index)
                if tracker is not None:
                    tracker["lastAction"] = hero_event["action"]
                    if hero_event["action"] in ("call", "bet", "raise", "reraise", "allin"):
                        tracker["stableBet"] = float(hero_event.get("amount") or 0)
        active_player_count = self.table_state["activePlayerCount"]
        dealer_index = hand.get("dealerIndex", dealer_index)
        position_seats = self._current_hand_position_seats(seats)
        hero_position = position_for(
            position_seats, hero_index, dealer_index,
            self._straddle_seat_for_position(position_seats, dealer_index))
        hand["heroPosition"] = hero_position
        self._observe_hero_range(hand.get("id"), hero_cards, hero_position)
        with self.capture_lock:
            latest_frame = self.latest_table_frame.copy() if self.latest_table_frame is not None else frame
        if latest_frame.shape[:2] == frame.shape[:2] and not np.array_equal(latest_frame, frame):
            latest_buttons = self._recognize_action_buttons_fast(latest_frame)
            if latest_buttons:
                buttons = latest_buttons
                call_button = next((button for button in buttons if button["kind"] == "call" and isinstance(button.get("value"), (int, float))), None)
                call_amount = call_button["value"] if call_button else 0.0 if any(button["kind"] == "check" for button in buttons) else None
        with self.action_state_lock:
            history_events = self.pending_history_events
            self.pending_history_events = []
        self.history_store.observe(hand, seats, history_events, pot, board_cards, hero_cards)
        rake_players = max(2, int(active_player_count or 0),
                           sum(1 for seat in seats if not seat.get("empty")))
        rake = lookup_rake(self.blind_amounts.get("small"), self.blind_amounts.get("big"),
                           self.blind_ante, rake_players,
                           self._effective_blind_straddle(seats),
                           self.blind_currency, self.table_play)
        if rake:
            self.rake_rate, self.rake_cap = rake["rate"], rake["cap"]
            self.rake_players = rake_players
            self.rake_source = "blind_table"
        raw = {
            "status": f"v{APP_VERSION} · {active_player_count}人 · {width}×{height} · {capture_bbox[0]},{capture_bbox[1]} · {int((time.time() - started) * 1000)}ms",
            "layout": self.layout,
            "seats": seats,
            "seatStateFrameCapturedAt": seat_frame_captured_at,
            "seatStateFrameSequence": seat_frame_sequence,
            "seatStateHandId": seat_hand_id,
            "seatStateStreet": seat_street,
            "activePlayerCount": active_player_count,
            "dealerIndex": dealer_index,
            "dealerReliable": bool(dealer_index is not None and
                                   self.dealer_monitor_current == dealer_index and
                                   self.dealer_monitor_candidate is None and
                                   not self.dealer_conflict),
            "heroPosition": hero_position,
            "heroPositionName": {"dealer": "庄家位", "small_blind": "小盲位", "big_blind": "大盲位",
                                 "straddle": "Straddle位",
                                 "under_the_gun": "枪口位", "under_the_gun_plus_one": "枪口后一位",
                                 "middle": "中间位", "hijack": "劫位", "cutoff": "关煞位",
                                 "unknown": "位置未确认"}.get(hero_position, "位置未确认"),
            "pot": pot,
             "rakeRate": self.rake_rate,
             "rakeCap": self.rake_cap,
             "rakePlayers": getattr(self, "rake_players", None),
             "rakeSource": getattr(self, "rake_source", None),
            "tablePlay": getattr(self, "table_play", None),
            "tableNumber": getattr(self, "table_number", None),
            "tableIdentityOcr": getattr(self, "table_identity_ocr", ""),
            "blindTextRaw": self.blind_text_raw,
            "blindSmall": self.blind_amounts.get("small"),
            "blindBig": self.blind_amounts.get("big"),
            "blindStraddle": self._effective_blind_straddle(seats),
            "blindAnte": getattr(self, "blind_ante", None),
            "centerMoney": list((self.cached_state or {}).get("centerMoney", [])),
            "callAmount": call_amount,
            "minRaiseTo": minimum_raise_to(
                self.action_log, hand["id"], hand["street"], self.blind_amounts.get("big")
            ),
            "preflopFullRaiseCount": full_raise_count(
                self.action_log, hand["id"], "preflop", self.blind_amounts.get("big")
            ),
            "boardCards": board_cards,
            "heroCards": hero_cards,
            "visibleHeroCards": observed_hero_cards,
            "street": hand["street"],
            "newHand": hand["newHand"],
            "dealerChanged": hand["dealerChanged"],
            "dealerConflict": hand.get("dealerConflict"),
            "handActive": hand["active"],
            "handId": hand["id"],
            "buttons": buttons,
            "actionLog": list(self.action_log), "actionCandidates": self.action_candidates[-30:],
            "winners": list(self.hand_winners),
            "seatDiagnostics": [seat.get("diagnostic", {
                "seat": seat.get("index", -1) + 1,
                "status": seat.get("occupancy", "unknown"),
                "previousBet": None,
                "currentBet": seat.get("streetBet"),
                "action": seat.get("action", "waiting"),
                "confidence": 0.0,
                "evidence": "diagnostic_unavailable",
            }) for seat in seats],
            "opponentProfiles": self.history_store.summaries(seats),
            "historyStatus": self.history_store.status(),
            "unactedPlayers": self._unacted_count(seats),
                "expectedActionSeat": (self.formal_expected_seat + 1
                                       if self.formal_expected_seat is not None and not turn_confirmed else
                                       hero_index + 1 if turn_confirmed else None),
                "heroActsAfterExpected": (self.formal_expected_seat is not None and not turn_confirmed and
                                           self._next_tracker_seat(self.formal_expected_seat) == hero_index),
            "heroAction": hero_action,
            "participating": participating,
            "heroAvatarMatch": hero_avatar_match,
            "participationEvidence": self.hero_evidence,
            "spectator": spectator,
            "reliable": strategy_inputs_reliable,
            "actionable": strategy_inputs_reliable and self._official_action_cluster(buttons),
            "identityReliable": all(seat.get("confidence", 0) >= .55 for seat in seats if seat.get("name")),
            "specialScene": None,
        }
        snapshot = raw
        raw["slowUpdatedAt"] = time.time()
        raw["fieldStatus"] = self.fields.snapshot()
        self.last_snapshot = raw
        if seat_hand_id == self.hand_state.get("id"):
            self.force_slow_snapshot = False
        if self.overlay is not None:
            self.overlay.update(self._overlay_bbox(), visible=True)
        return snapshot

    def _publish_rake_from_blinds(self, players=None, confidence=.9, source="blind_table",
                                  **context):
        counts = [players, self.table_state.get("activePlayerCount"),
                  len(self._current_hand_eligible_indices()),
                  sum(tracker.get("occupancy") == "occupied"
                      for tracker in self.seat_trackers.values()),
                  self.rake_players]
        rake_players = next((int(value) for value in counts
                             if isinstance(value, (int, float)) and 2 <= value <= 8), None)
        if rake_players is None:
            return None
        rake = lookup_rake(self.blind_amounts.get("small"), self.blind_amounts.get("big"),
                           self.blind_ante, rake_players,
                           self.blind_straddle if rake_players >= 4 else None,
                           self.blind_currency, self.table_play)
        if rake is None:
            return None
        self.rake_rate, self.rake_cap = rake["rate"], rake["cap"]
        self.rake_players, self.rake_source = rake_players, "blind_table"
        confirmed = {**context, "confirmed_at": time.time()}
        for field, value in (("rakeRate", self.rake_rate), ("rakeCap", self.rake_cap),
                             ("rakePlayers", self.rake_players),
                             ("rakeSource", self.rake_source)):
            self.fields.commit(field, value, confidence, source, True, **confirmed)
        return rake

    def _capture_slow_state(self):
        with self.capture_lock:
            frame = self.latest_table_frame.copy() if self.latest_table_frame is not None else None
            captured_at = self.latest_frame_captured_at
            frame_sequence = self.latest_frame_sequence
        if frame is None:
            return {"status": "正在自动寻找绿色牌桌", "seats": [], "reliable": False,
                    "spectator": True, "slowUpdatedAt": time.time()}
        special_scene = self._detect_special_scene(frame)
        if special_scene:
            return {"status": f"v{APP_VERSION} · 场景遮挡，暂停慢通道身份采集",
                    "specialScene": special_scene, "slowUpdatedAt": time.time()}
        action_pressure = False
        if self._slow_action_pressure():
            action_pressure = True
        if (action_pressure and not self.initial_identity_pending and
                not self.table_identity_reacquiring):
            return {"status": f"v{APP_VERSION} · 快通道优先，暂缓慢通道OCR",
                    "slowUpdatedAt": time.time()}
        started = time.time()
        height, width = frame.shape[:2]
        self._update_layout(self._detect_layout(frame))
        if self.initial_identity_pending:
            self._start_startup_chip_scan(frame.copy(), captured_at, frame_sequence)

        blind_box = self._reviewed_slot_box((210, 1060, 690, 1150), width, height)
        blind_crop = frame[blind_box[1]:blind_box[3], blind_box[0]:blind_box[2]]
        blind_items = self._ocr_items(blind_crop)
        slot_parsed_blinds = next((parsed for item in blind_items
                                   if (parsed := parse_blind_text(item.get("text"))) is not None), None)

        table_info_box = self._reviewed_slot_box((250, 1015, 650, 1100), width, height)
        table_info_crop = frame[table_info_box[1]:table_info_box[3], table_info_box[0]:table_info_box[2]]
        enlarged = cv2.resize(table_info_crop, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(enlarged, cv2.COLOR_BGR2GRAY)
        enhanced = cv2.convertScaleAbs(gray, alpha=1.8, beta=15)
        candidates = []
        for variant in (enlarged, enhanced,
                        cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]):
            text, confidence = self._ocr(variant)
            if text:
                candidates.append((text, confidence))
            if parse_table_play(text) and parse_table_number(text):
                break
        table_info_text, table_info_confidence = max(candidates, key=lambda item: (
            bool(parse_table_play(item[0])), bool(parse_table_number(item[0])), item[1], len(item[0])
        ), default=("", 0.0))
        table_parsed_blinds = parse_blind_text(table_info_text)
        parsed_blinds = max(
            (parsed for parsed in (slot_parsed_blinds, table_parsed_blinds) if parsed is not None),
            key=lambda parsed: (int(parsed.get("straddle") is not None) + int(parsed.get("hasAnte")),
                                len(str(parsed.get("raw") or ""))),
            default=None,
        )
        blind_from_table_info = parsed_blinds is table_parsed_blinds and table_parsed_blinds is not None
        if parsed_blinds is not None:
            ante = parsed_blinds.get("ante") if parsed_blinds.get("hasAnte") else 0.0
            candidate = (parsed_blinds["small"], parsed_blinds["big"],
                         parsed_blinds.get("straddle"), ante,
                         parsed_blinds.get("currency", "usd"))
            if candidate == self.blind_text_candidate:
                self.blind_text_frames += 1
            else:
                self.blind_text_candidate = candidate
                self.blind_text_frames = 1
            if (self.blind_text_frames >= 2 or not self.blind_text_raw or
                    self.blind_amounts.get("big") in (None, 0)):
                self.blind_amounts.update(small=candidate[0], big=candidate[1])
                self.blind_straddle = candidate[2]
                self.blind_ante = candidate[3]
                self.blind_currency = candidate[4]
                self.blind_text_raw = parsed_blinds["raw"]
        self.table_identity_ocr = table_info_text
        self.fields.commit("tableIdentityOcr", table_info_text, table_info_confidence,
                           "reviewed_table_info_slot", bool(table_info_text))
        parsed_play = parse_table_play(table_info_text)
        if parsed_play is not None:
            self.table_play = parsed_play
        parsed_number = parse_table_number(table_info_text)
        self._observe_table_number(parsed_number)
        table_context = {"observed_at": captured_at, "frameSequence": frame_sequence}
        if parsed_play is not None:
            self.fields.commit("tablePlay", self.table_play, table_info_confidence,
                               "reviewed_table_info_slot", True, **table_context)
        if parsed_number is not None and self.table_number_frames >= 2:
            self.fields.commit("tableNumber", self.table_number, table_info_confidence,
                               "reviewed_table_info_slot+two_frame_consensus", True,
                               **table_context)
        blind_confidence = max(
            max((float(item.get("confidence") or 0) for item in blind_items), default=0.0),
            float(table_info_confidence or 0) if blind_from_table_info and parsed_blinds else 0.0,
        )
        blind_valid = bool(self.blind_text_raw and self.blind_amounts.get("small") and
                           self.blind_amounts.get("big") and self.blind_text_frames >= 2)
        current_blind_evidence = parsed_blinds is not None and blind_valid
        if current_blind_evidence:
            self.fields.commit("blindTextRaw", self.blind_text_raw, blind_confidence,
                               "reviewed_blind_slot+two_frame_consensus", True,
                               **table_context)
            for field, value in (("blindSmall", self.blind_amounts.get("small")),
                                 ("blindBig", self.blind_amounts.get("big")),
                                 ("blindStraddle", self.blind_straddle),
                                 ("blindAnte", self.blind_ante)):
                value_valid = ((value is None and field == "blindStraddle") or
                               isinstance(value, (int, float)))
                if value_valid:
                    self.fields.commit(field, value, blind_confidence,
                                       "parsed_blind_text", True, **table_context)

        if current_blind_evidence:
            self._publish_rake_from_blinds(confidence=blind_confidence,
                                           source="blind_table+existing_player_count",
                                           **table_context)

        table_basics = {
            "status": f"v{APP_VERSION} · 启动阶段优先识别牌桌基础信息",
            "layout": self.layout,
            "tablePlay": self.table_play,
            "tableNumber": self.table_number,
            "tableIdentityOcr": self.table_identity_ocr,
            "blindTextRaw": self.blind_text_raw,
            "blindSmall": self.blind_amounts.get("small"),
            "blindBig": self.blind_amounts.get("big"),
            "blindStraddle": self._effective_blind_straddle(),
            "blindAnte": self.blind_ante,
            "rakeRate": self.rake_rate,
            "rakeCap": self.rake_cap,
            "rakePlayers": getattr(self, "rake_players", None),
            "rakeSource": getattr(self, "rake_source", None),
            "activePlayerCount": self.table_state["activePlayerCount"],
            "specialScene": None,
            "slowUpdatedAt": time.time(),
        }
        with self.state_lock:
            hero_turn_active = bool((self.cached_state or {}).get("visualHeroTurn"))
        identity_pressure = bool(
            hero_turn_active or
            getattr(self.action_ocr_queue, "unfinished_tasks", 0) or
            getattr(self.avatar_ocr_queue, "unfinished_tasks", 0) or
            self.action_ocr_pending_seats or self.avatar_ocr_pending_seats
        )
        if identity_pressure:
            return table_basics

        identity = self._capture_slow_identity_state(
            frame, captured_at, frame_sequence, started,
            include_names=not self.initial_identity_pending)
        identity_seats = identity.get("seats", [])
        identity_count = sum(seat.get("occupancy") == "occupied" for seat in identity_seats)
        if 2 <= identity_count <= 8:
            self.table_state["activePlayerCount"] = identity_count
        if current_blind_evidence:
            self._publish_rake_from_blinds(identity_count, blind_confidence,
                                           "blind_table+identity_player_count",
                                           **table_context)
        self._flush_history_state(identity_seats)
        identity.update({
            **table_basics,
            "status": f"v{APP_VERSION} · 慢通道仅更新身份与牌桌信息",
            "blindStraddle": self._effective_blind_straddle(identity_seats),
            "activePlayerCount": self.table_state["activePlayerCount"],
            "opponentProfiles": self.history_store.summaries(identity_seats),
            "historyStatus": self.history_store.status(),
            "slowUpdatedAt": time.time(),
        })
        with self.state_lock:
            self.cached_state = dict(self.cached_state or {})
            self.cached_state.update({key: value for key, value in identity.items()
                                      if key != "seats"})
        return identity

    def _update_layout(self, observed):
        table = self.table_state
        if observed == table["layout"]:
            table["pendingLayout"], table["pendingFrames"] = None, 0
            return
        if observed == table["pendingLayout"]:
            table["pendingFrames"] += 1
        else:
            table["pendingLayout"], table["pendingFrames"] = observed, 1
        if table["pendingFrames"] >= 2:
            self.layout = table["layout"] = observed
            table["pendingLayout"], table["pendingFrames"] = None, 0
            self.seat_trackers.clear()

    def _update_table_state(self, observations, hero_index, participating, hero_has_cards=False):
        result = []
        for observed in observations:
            index = observed["index"]
            tracker = self.seat_trackers.setdefault(index, {
                "occupancy": "unknown", "pendingOccupancy": None, "occupancyFrames": 0,
                "name": "", "chips": None, "avatar": "", "avatarHash": "",
                "stableBet": 0.0, "pendingBet": None, "betFrames": 0,
                "active": False, "lastAction": "waiting", "lastEvidence": "none",
            })
            evidence = bool(observed.get("seatPresent") or observed.get("name") or
                            observed.get("chips") is not None or observed.get("avatarPresent"))
            hero_confirmed = index == hero_index and (hero_has_cards or participating)
            candidate = "occupied" if hero_confirmed else "empty" if observed.get("empty") else "occupied" if evidence else "unknown"
            if candidate != "unknown":
                immediate = hero_confirmed or observed.get("empty") or evidence
                confirmations = 1 if immediate else 2
                for _ in range(confirmations):
                    self._set_seat_occupancy(index, candidate, "slow_seat_state")
            if tracker["occupancy"] == "occupied":
                observed_name = observed.get("name") or ""
                if not self._valid_player_name(observed_name):
                    observed_name = ""
                previous_name = tracker.get("name") or ""
                name_changed = bool(observed_name and "mvp" not in observed_name.casefold() and
                                    previous_name not in ("", "MVP", observed_name))
                if observed_name and ("mvp" not in observed_name.casefold() or not tracker["name"]):
                    tracker["name"] = observed_name
                self._observe_confirmed_profile_name(index, observed_name, tracker)
                if self.profile_confirmed_names.get(index):
                    tracker["name"] = self.profile_confirmed_names[index]
                if observed.get("chips") is not None:
                    tracker["chips"] = observed["chips"]
                observed_hash = observed.get("avatarHash") or ""
                current_hash = tracker.get("avatarHash") or ""
                if observed_hash and (not current_hash or name_changed or
                                      self._avatar_hash_distance(current_hash, observed_hash) <= 8):
                    if not current_hash or name_changed:
                        tracker["avatarHash"] = observed_hash
                    if observed.get("avatar"):
                        tracker["avatar"] = observed["avatar"]
            stable = dict(observed)
            stable.update({key: tracker[key] for key in ("name", "chips", "avatar", "avatarHash")})
            stable["occupancy"] = tracker["occupancy"]
            stable["empty"] = tracker["occupancy"] == "empty"
            result.append(stable)
        self.table_state["activePlayerCount"] = sum(seat["occupancy"] == "occupied" for seat in result)
        return result

    @staticmethod
    def _valid_player_name(name):
        normalized = re.sub(r"\s+", "", name or "")
        blocked = ("等待中", "暂离", "详细数据", "可用余额", "保险", "购买中", "outs", "一对", "两对",
                   "三条", "顺子", "同花", "葫芦", "四条", "同花顺", "弃牌", "让牌", "跟注", "下注", "加注")
        return (bool(normalized) and normalized.casefold() not in ("mvp", "jp") and
                not any(word.casefold() in normalized.casefold() for word in blocked))

    def _update_hand_state(self, seats, hero_cards, board_cards, pot, participating, dealer_index=None):
        if not hasattr(self, "hand_machine"):
            self.hand_machine = HandMachine()
            old = getattr(self, "hand_state", {})
            self.hand_machine.active = bool(old.get("active"))
            self.hand_machine.hand_id = int(old.get("id", 0))
            self.hand_machine.street = old.get("street", "waiting")
            self.hand_machine.board = list(old.get("boardCards", []))
            self.hand_machine.hero = list(old.get("heroCards", []))
            self.hand_machine.pot = old.get("pot")
        stable_bets = [float(seat.get("streetBet") or 0) for seat in seats if seat.get("occupancy") == "occupied"]
        dealer_changed = False
        dealer_conflict = None
        current_dealer = getattr(self, "hand_dealer_index", None)
        current_second = getattr(self, "recording_second", None)
        elapsed = (current_second - self.hand_started_second
                   if current_second is not None and self.hand_started_second is not None else None)
        if dealer_index is not None and current_dealer is not None and dealer_index != current_dealer:
            expected = self._next_occupied_seat(seats, current_dealer)
            if dealer_index == expected and (elapsed is None or elapsed >= 5.0):
                dealer_changed = True
            elif dealer_index == expected:
                dealer_index = current_dealer
            else:
                dealer_conflict = {"previous": current_dealer + 1,
                                   "observed": dealer_index + 1,
                                   "expected": expected + 1 if expected is not None else None}
        suppress_new_hand = bool(self.hand_machine.active and not dealer_changed)
        result = self.hand_machine.update(participating, hero_cards, board_cards, pot,
                                          sum(value > 0 for value in stable_bets), force_new_hand=dealer_changed,
                                          suppress_new_hand=suppress_new_hand)
        if result["newHand"] and not dealer_changed:
            result["newHand"] = False
        if dealer_index is not None and (current_dealer is None or dealer_changed):
            self.hand_dealer_index = dealer_index
            self.last_dealer_index = dealer_index
            self.fast_dealer_locked_at = time.time()
            self.hand_started_second = getattr(self, "recording_second", None)
        result["dealerChanged"] = dealer_changed
        result["dealerConflict"] = dealer_conflict
        result["dealerIndex"] = self.hand_dealer_index
        self.dealer_conflict = dealer_conflict
        self.hand_state.update({key: result[key] for key in ("active", "id", "street", "pot", "boardCards", "heroCards")})
        if result["newHand"] and dealer_changed:
            self.locked_hero_cards = []
            self.locked_hero_hand_id = result["id"]
            self.card_candidates["heroCards"] = []
            self.card_candidate_frames["heroCards"] = 0
            self.card_published["heroCards"] = []
            self.card_visible["heroCards"] = []
            self.card_visible_frame_sequence = -1
        if result["newHand"]:
            for seat in seats:
                occupancy = seat.get("occupancy")
                if occupancy in ("occupied", "empty"):
                    self._set_seat_occupancy(
                        seat["index"], occupancy, "slow_seat_state",
                        observed_at=getattr(self, "latest_frame_captured_at", None),
                        video_second=getattr(self, "recording_second", None),
                    )
            self._close_action_timeline(
                "state_machine_new_hand",
                observed_at=getattr(self, "latest_frame_captured_at", None),
                frame_sequence=getattr(self, "latest_frame_sequence", 0),
                video_second=getattr(self, "recording_second", None),
            )
            self._start_action_timeline(
                result["id"],
                observed_at=getattr(self, "latest_frame_captured_at", None),
                frame_sequence=getattr(self, "latest_frame_sequence", 0),
                video_second=getattr(self, "recording_second", None),
            )
            self.reaction_estimate_cache_key = None
            self.reaction_estimate_cache = self._empty_reaction_estimates()
            self._mark_pipeline("hand_started", signal="state_machine", dealerIndex=self.hand_dealer_index,
                                frameSequence=getattr(self, "latest_frame_sequence", 0),
                                observedAt=getattr(self, "latest_frame_captured_at", None))
            self.hand_closed = False
            self.waiting_for_forced_bets = True
            self.forced_bet_seats = {}
            self._action_event_ledger().close_projection()
            self.action_log.clear()
            self.folded_seats.clear()
            self.hand_winners.clear()
            self.forced_bets_ready = False
            self.hand_started_second = getattr(self, "recording_second", None)
            self.last_fast_hand_start_second = self.hand_started_second
            self.pending.clear()
            self.stable.clear()
            getattr(self, "fast_action_signatures", {}).clear()
            for tracker in self.seat_trackers.values():
                eligible = (tracker["occupancy"] == "occupied" and
                            tracker.get("visualState") not in ("away", "waiting", "empty"))
                tracker.update(active=eligible, handEligible=eligible, lastAction="waiting")
            self.hand_participants[result["id"]] = {
                index for index, tracker in self.seat_trackers.items()
                if tracker.get("handEligible", True)
            }
            self.hand_player_counts[result["id"]] = len(self.hand_participants[result["id"]])
            small = self._next_tracker_seat(self.hand_dealer_index)
            big = self._next_tracker_seat(small) if small is not None else None
            self._set_forced_bet_seats(
                small, big, self._next_tracker_seat(big) if big is not None else None)
        elif result["streetChanged"]:
            for tracker in self.seat_trackers.values():
                tracker.update(lastAction="fold" if tracker.get("lastAction") == "fold" else "waiting",
                               stableBet=0.0, pendingBet=None, betFrames=0)
        return result

    @staticmethod
    def _next_occupied_seat(seats, dealer_index):
        occupied = {seat["index"] for seat in seats if seat.get("occupancy") == "occupied"}
        if dealer_index is None or not occupied:
            return None
        for offset in range(1, len(seats) + 1):
            candidate = (dealer_index + offset) % len(seats)
            if candidate in occupied:
                return candidate
        return None

    def _straddle_seat_for_position(self, seats, dealer_index):
        hand_id = self.hand_state.get("id")
        confirmed_events = [event for event in self.action_log
                            if event.get("handId") == hand_id and
                            event.get("action") == "straddle" and
                            isinstance(event.get("seat"), int) and
                            1 <= event.get("seat") <= len(TABLE_LAYOUTS[self.layout])]
        explicit_seats = {event["seat"] - 1 for event in confirmed_events}
        if len(explicit_seats) == 1:
            return next(iter(explicit_seats))
        if not self._straddle_allowed_for_hand(seats):
            return None
        enabled = isinstance(getattr(self, "blind_straddle", None), (int, float)) and self.blind_straddle > 0
        enabled = enabled or bool(confirmed_events)
        if not enabled:
            return None
        small = self._next_occupied_seat(seats, dealer_index)
        big = self._next_occupied_seat(seats, small)
        return self._next_occupied_seat(seats, big)

    def _hand_player_count(self, seats=None):
        hand_id = self.hand_state.get("id")
        locked_count = self.hand_player_counts.get(hand_id)
        if isinstance(locked_count, int) and 2 <= locked_count <= 8:
            return locked_count
        participants = self.hand_participants.get(hand_id, set())
        if len(participants) >= 2:
            return len(participants)
        if seats is not None:
            count = sum(seat.get("occupancy") == "occupied" and not seat.get("empty")
                        for seat in seats)
            if count >= 2:
                return count
        counts = (self.table_state.get("activePlayerCount"),
                  sum(tracker.get("occupancy") == "occupied"
                      for tracker in self.seat_trackers.values()))
        return next((int(value) for value in counts
                     if isinstance(value, (int, float)) and 2 <= value <= 8), 0)

    def _straddle_allowed_for_hand(self, seats=None):
        if self._hand_player_count(seats) >= 4:
            return True
        hand_id = self.hand_state.get("id")
        has_event = any(event.get("handId") == hand_id and
                        event.get("action") == "straddle"
                        for event in self.action_log)
        occupied = sum(seat.get("occupancy") == "occupied" and not seat.get("empty")
                       for seat in (seats or []))
        return bool(has_event and occupied >= 4)

    def _effective_blind_straddle(self, seats=None):
        value = getattr(self, "blind_straddle", None)
        return value if self._straddle_allowed_for_hand(seats) and isinstance(
            value, (int, float)) and value > 0 else None

    def _update_action_state(self, seats, reset=False, pot_after=None):
        if not hasattr(self, "action_state_lock"):
            self.action_state_lock = threading.RLock()
            self.pending_history_events = []
            self.fast_action_signatures = {}
        if not hasattr(self, "blind_amounts"):
            self.blind_amounts = {"small": None, "big": None}
        with self.action_state_lock:
            return self._update_action_state_locked(seats, reset, pot_after)

    def _sync_fast_street(self, board_cards):
        current_second = getattr(self, "recording_second", None)
        captured_at = getattr(self, "latest_frame_captured_at", None)
        changed_at = (current_second if current_second is not None else
                      captured_at if captured_at is not None else time.time())
        street = {0: "preflop", 3: "flop", 4: "turn", 5: "river"}.get(len(board_cards))
        current = self.hand_state.get("street", "waiting")
        order = {"waiting": -1, "preflop": 0, "flop": 1, "turn": 2, "river": 3}
        if street is None or order.get(street, -1) <= order.get(current, -1):
            return
        with self.action_state_lock:
            repaired_continuations = self._reconcile_closed_street_continuations(
                self.hand_state.get("id"), current, changed_at,
                getattr(self, "latest_frame_sequence", 0), current_second)
            if repaired_continuations:
                self._rebuild_action_timeline(self.hand_state.get("id"), current)
            confirmed_terminal_indices = {
                (item.get("seat") or 1) - 1
                for item in self.action_log
                if item.get("handId") == self.hand_state.get("id") and
                item.get("action") in ("fold", "allin") and
                not item.get("visualCandidate")
            }
            unresolved = set()
            expected = getattr(self, "formal_expected_seat", None)
            if expected is not None:
                for _ in range(len(TABLE_LAYOUTS[self.layout])):
                    tracker = self.seat_trackers.get(expected, {})
                    if (tracker.get("occupancy") == "occupied" and tracker.get("handEligible", True) and
                            expected not in confirmed_terminal_indices):
                        unresolved.add(expected)
                    expected = self._next_opponent_seat(expected)
                    if expected is None or expected == self.formal_expected_seat:
                        break
            prior_highest = max(
                (float(tracker.get("stableBet") or 0) for index, tracker in self.seat_trackers.items()
                 if tracker.get("occupancy") == "occupied" and tracker.get("handEligible", True) and
                 index not in confirmed_terminal_indices),
                default=0.0,
            )
            forced_fold_seats = {
                index for index in unresolved
                if float(self.seat_trackers.get(index, {}).get("stableBet") or 0) + .001 < prior_highest
            }
            self.prior_street_unresolved = {
                "street": current, "seats": unresolved,
                "forcedFoldSeats": forced_fold_seats,
                "changedAt": changed_at,
            }
            hero_index = 4 if self.layout == "8max" else 3
            highest_aggression = max(
                (float(item.get("amount") or 0) for item in self.action_log
                 if item.get("handId") == self.hand_state.get("id") and
                 item.get("street") == current and item.get("action") in
                 ("bet", "raise", "reraise", "allin")),
                default=0.0,
            )
            hero_prior = max(
                (float(item.get("amount") or 0) for item in self.action_log
                 if item.get("handId") == self.hand_state.get("id") and
                 item.get("street") == current and item.get("seat") == hero_index + 1),
                default=0.0,
            )
            hero_call_deficit = highest_aggression > hero_prior + max(.001, highest_aggression * .02)
            candidate = next((item for item in reversed(self.action_candidates)
                              if item.get("handId") == self.hand_state.get("id") and
                              item.get("street") == current and item.get("seat") == hero_index + 1 and
                              item.get("action") == "hero_action_unresolved" and
                              "check" in item.get("possibleActions", []) and not item.get("promoted") and
                              self.formal_expected_seat == hero_index), None)
            if candidate and not hero_call_deficit:
                event = dict(candidate)
                event.update(action="check", amount=0.0, increase=0.0, confidence=.95,
                             evidence="official_check_button_disappeared+next_street_started",
                             chainStatus="rule_confirmed", strategyEligible=True)
                if self._append_action_event(event):
                    candidate["promoted"] = True
                    self.seat_trackers.get(hero_index, {})["lastAction"] = "check"
            call_candidate = next((item for item in reversed(self.action_candidates)
                                   if item.get("handId") == self.hand_state.get("id") and
                                   item.get("street") == current and item.get("seat") == hero_index + 1 and
                                   item.get("action") == "hero_action_unresolved" and
                                   ("call" in item.get("possibleActions", []) or
                                    (hero_call_deficit and "check" in item.get("possibleActions", []))) and
                                   not item.get("promoted") and
                                    self.formal_expected_seat == hero_index), None)
            release_context = getattr(self, "hero_button_release_context", None)
            if not (release_context and
                    release_context.get("handId") == self.hand_state.get("id") and
                    release_context.get("street") == current and
                    release_context.get("seat") == hero_index + 1):
                release_context = None
            call_button = next((item for item in (release_context or {}).get("buttons", [])
                                if item.get("kind") == "call" and
                                isinstance(item.get("value"), (int, float))), None)
            if call_candidate or call_button:
                highest = max((float(item.get("amount") or 0) for item in self.action_log
                               if item.get("handId") == self.hand_state.get("id") and
                               item.get("street") == current and item.get("action") in
                               ("bet", "raise", "reraise", "allin")), default=0.0)
                prior = max((float(item.get("amount") or 0) for item in self.action_log
                             if item.get("handId") == self.hand_state.get("id") and
                              item.get("street") == current and item.get("seat") == hero_index + 1),
                             default=0.0)
                call_delta = highest - prior
                amount_matches = bool(
                    call_button and call_delta > 0 and
                    abs(float(call_button["value"]) - call_delta) <= max(.05, call_delta * .04)
                )
                hero_continued = bool(
                    self.participating_locked or len(self.card_published.get("heroCards", [])) == 2 or
                    hero_index in self.hand_participants.get(self.hand_state.get("id"), set())
                )
                hero_terminal = any(
                    item.get("handId") == self.hand_state.get("id") and
                    item.get("street") == current and item.get("seat") == hero_index + 1 and
                    item.get("action") in ("fold", "allin")
                    for item in self.action_log
                )
                if highest > prior and hero_continued and not hero_terminal and (
                        call_candidate or amount_matches):
                    event = dict(call_candidate or {
                        "time": (release_context or {}).get("observedAt", changed_at),
                        "observedAt": (release_context or {}).get("observedAt", changed_at),
                        "videoSecond": (release_context or {}).get("videoSecond"),
                        "handId": self.hand_state.get("id"), "street": current,
                        "sequence": 1, "seat": hero_index + 1,
                        "name": self.seat_trackers.get(hero_index, {}).get("name", "Zixia888"),
                        "actionButtonSequence": (release_context or {}).get("actionButtonSequence"),
                        "buttonLastVisibleFrameSequence": (release_context or {}).get("lastVisibleFrameSequence"),
                    })
                    event.update(action="call", amount=highest, increase=highest - prior, confidence=.95,
                                  evidence="official_call_button_disappeared+next_street_started",
                                  chainStatus="rule_confirmed", strategyEligible=True)
                    if self._append_action_event(event):
                        if call_candidate:
                            call_candidate["promoted"] = True
                        self.seat_trackers.get(hero_index, {}).update(lastAction="call", stableBet=highest)
            self.hero_button_release_context = None
            self.active_color_actions = {index: None for index in range(len(TABLE_LAYOUTS[self.layout]))}
            self.last_color_event_seat = None
            with self.action_ocr_pending_lock:
                self.action_ocr_deferred_jobs.clear()
            for candidate in self.action_candidates:
                if (candidate.get("handId") == self.hand_state.get("id") and
                        candidate.get("street") == current and not candidate.get("promoted")):
                    if (candidate.get("action") == "fold" and
                            candidate.get("evidenceFrames", 0) >= 3 and
                            candidate.get("evidenceSignals", {}).get("avatarText") and
                            (current_second is None or
                             candidate.get("lastSeenSecond", candidate.get("videoSecond")) is None or
                             current_second - candidate.get("lastSeenSecond", candidate.get("videoSecond")) <= 2.0)):
                        event = dict(candidate)
                        event.pop("visualCandidate", None)
                        event.update(chainStatus="rule_confirmed", strategyEligible=True,
                                     confidence=max(float(event.get("confidence") or 0), .86),
                                     evidence=f"{event.get('evidence', '')}+next_street_closed")
                        if self._append_action_event(event, resolve_prior=False):
                            candidate["promoted"] = True
                            tracker = self.seat_trackers.get((candidate.get("seat") or 1) - 1)
                            if tracker is not None:
                                tracker["lastAction"] = "fold"
                            continue
                    candidate["expired"] = True
            self.avatar_fold_frames = {index: 0 for index in range(len(TABLE_LAYOUTS[self.layout]))}
            self.avatar_contrast_history = {index: deque(maxlen=20) for index in range(len(TABLE_LAYOUTS[self.layout]))}
            self.avatar_state_latched = {index: False for index in range(len(TABLE_LAYOUTS[self.layout]))}
            self.avatar_state_clear_frames = {index: 0 for index in range(len(TABLE_LAYOUTS[self.layout]))}
            self.hand_state["street"] = street
            self.hand_state["boardCards"] = list(board_cards)
            self.hand_machine.street = street
            self.hand_machine.board = list(board_cards)
            latest_sequence = getattr(self, "latest_frame_sequence", 0)
            last_button_sequence = getattr(
                self, "hero_button_last_visible_frame_sequence", None)
            self.visual_turn_detected = False
            self.visual_turn_hand_id = None
            self.visual_turn_street = None
            self.hero_button_last_visible_street = None
            self.action_button_missing_frames = 0
            self.action_button_detected_at = None
            self.action_button_state_published_at = None
            self.action_button_frame_captured_at = None
            self.action_button_frame_received_at = None
            self.action_button_frame_sequence = None
            self.last_street_change_at = time.time()
            self._mark_pipeline("street_changed", handId=self.hand_state.get("id"),
                                fromStreet=current, toStreet=street,
                                videoSecond=getattr(self, "recording_second", None),
                                frameSequence=getattr(self, "latest_frame_sequence", 0))
            self._transition_action_timeline(
                self.hand_state.get("id"), current, street,
                observed_at=changed_at,
                frame_sequence=getattr(self, "latest_frame_sequence", 0),
                video_second=current_second,
            )
            confirmed_terminal_seats = {
                (item.get("seat") or 1) - 1: item.get("action")
                for item in self.action_log
                if item.get("handId") == self.hand_state.get("id") and
                item.get("action") in ("fold", "allin") and
                not item.get("visualCandidate")
            }
            for index, tracker in self.seat_trackers.items():
                prior_action = tracker.get("lastAction")
                confirmed_terminal = confirmed_terminal_seats.get(index)
                tracker.update(lastAction=confirmed_terminal or
                               ("fold" if prior_action == "fold" else "waiting"),
                               stableBet=0.0, pendingBet=None, betFrames=0,
                               pendingVisualBet=None, pendingVisualBetHand=None,
                               pendingVisualBetStreet=None, pendingVisualBetSecond=None)
            active = [index for index, tracker in self.seat_trackers.items()
                      if tracker.get("occupancy") == "occupied" and
                      tracker.get("lastAction") not in ("fold", "allin")]
            self.formal_expected_seat = self._next_occupied_seat_from_indices(
                active, self.hand_dealer_index, len(TABLE_LAYOUTS[self.layout]))

    def _reconcile_closed_street_continuations(self, hand_id, street,
                                               observed_at=None,
                                               frame_sequence=None,
                                               video_second=None):
        events = [item for item in self.action_log
                  if item.get("handId") == hand_id and item.get("street") == street]
        investment_actions = {"blind", "post_blind", "straddle", "call",
                              "bet", "raise", "reraise", "allin"}
        highest = max((float(item.get("amount") or 0) for item in events
                       if item.get("action") in investment_actions), default=0.0)
        if highest <= 0:
            return False
        changed = False
        appended = []
        for seat in {item.get("seat") for item in events if item.get("seat")}:
            voluntary = [item for item in events if item.get("seat") == seat and
                         item.get("action") not in ("blind", "post_blind", "straddle")]
            if not voluntary:
                continue
            latest = voluntary[-1]
            tracker = self.seat_trackers.get(seat - 1, {})
            if latest.get("action") == "fold" or tracker.get("visualState") == "allin":
                continue
            contradicted = [item for item in voluntary if item.get("action") == "fold" and
                            item.get("inferred") and item is not latest]
            if contradicted:
                self.action_log[:] = [item for item in self.action_log if item not in contradicted]
                events = [item for item in events if item not in contradicted]
                self.folded_seats.discard(seat)
                changed = True
            if (latest.get("action") != "call" or
                    not isinstance(latest.get("amount"), (int, float)) or
                    float(latest["amount"]) >= highest - max(.001, highest * .02)):
                continue
            prior = max((float(item.get("amount") or 0) for item in events
                         if item.get("seat") == seat and
                         item.get("action") in investment_actions), default=0.0)
            repaired = {
                "time": time.time(),
                "observedAt": observed_at if observed_at is not None else time.time(),
                "recognizedAt": time.time(), "confirmedAt": time.time(),
                "frameSequence": (frame_sequence if frame_sequence is not None else
                                  getattr(self, "latest_frame_sequence", 0)),
                "videoSecond": video_second,
                "handId": hand_id, "street": street, "seat": seat,
                "name": tracker.get("name", latest.get("name", "")),
                "action": "call", "amount": highest,
                "increase": max(0.0, highest - prior),
                "confidence": max(.9, float(latest.get("confidence") or 0)),
                "inferred": True,
                "evidence": "next_street_proved_second_call_to_final_price",
                "chainStatus": "rule_confirmed", "strategyEligible": True,
                "orderConflict": False,
            }
            self.action_log.append(repaired)
            events.append(repaired)
            appended.append(repaired)
            tracker.update(lastAction="call", stableBet=highest)
            changed = True
        if appended:
            self._commit_formal_action_ledger(appended[-1])
        return changed

    def _start_hand_from_fast_dealer(self, dealer_index, boundary_at=None):
        with self.action_state_lock:
            current_second = getattr(self, "recording_second", None)
            if (current_second is not None and
                    self.last_fast_hand_start_second is not None and
                    current_second - self.last_fast_hand_start_second < 3.0):
                return False
            previous_dealer = self.hand_dealer_index
            previous_board = list(self.card_published.get("boardCards", []))
            previous_hand_id = self.hand_state.get("id")
            expected = self.formal_expected_seat
            for _ in range(len(TABLE_LAYOUTS[self.layout])):
                candidate = next((item for item in reversed(self.action_candidates)
                                  if item.get("handId") == previous_hand_id and
                                  item.get("street") == self.hand_state.get("street") and
                                  item.get("seat") == (expected + 1 if expected is not None else None) and
                                  item.get("action") == "fold" and item.get("evidenceFrames", 0) >= 3 and
                                  item.get("evidenceSignals", {}).get("avatarText") and
                                  (current_second is None or
                                   item.get("lastSeenSecond", item.get("videoSecond")) is None or
                                   current_second - item.get("lastSeenSecond", item.get("videoSecond")) <= 2.0) and
                                  not item.get("promoted") and not item.get("expired")), None)
                if candidate is None:
                    unresolved_hero_action = next((item for item in reversed(self.action_candidates)
                                                   if item.get("handId") == previous_hand_id and
                                                   item.get("street") == self.hand_state.get("street") and
                                                   item.get("seat") == (expected + 1 if expected is not None else None) and
                                                   item.get("action") == "hero_action_unresolved" and
                                                   not item.get("expired")), None)
                    tracker = self.seat_trackers.get(expected, {}) if expected is not None else {}
                    chips = tracker.get("chips")
                    if (unresolved_hero_action or tracker.get("lastAction") in ("fold", "allin") or
                            tracker.get("visualState") == "allin" or
                            (chips is not None and float(chips) <= 0.01)):
                        expected = self._next_tracker_seat(expected)
                        continue
                    break
                promoted = dict(candidate)
                promoted.pop("visualCandidate", None)
                promoted.update(inferred=True, confidence=.88,
                                evidence="fold_visual_candidate+dealer_hand_closed")
                if not self._append_action_event(promoted, resolve_prior=False):
                    break
                candidate["promoted"] = True
                expected = self._next_tracker_seat(expected)
            if self.action_log:
                self.completed_hand_actions.append({"handId": previous_hand_id,
                                                    "dealerIndex": previous_dealer,
                                                    "events": [dict(item) for item in self.action_log]})
            if self.action_candidates:
                self.completed_hand_candidates.append({"handId": previous_hand_id,
                                                       "events": [dict(item) for item in self.action_candidates]})
            self._close_action_timeline(
                "next_hand_started", observed_at=boundary_at,
                frame_sequence=getattr(self, "latest_frame_sequence", 0),
                video_second=getattr(self, "recording_second", None))
            self.hand_machine.hand_id += 1
            self._mark_pipeline("hand_started", signal="dealer", dealerIndex=dealer_index,
                                frameSequence=getattr(self, "latest_frame_sequence", 0),
                                observedAt=getattr(self, "latest_frame_captured_at", None))
            self.hand_machine.active = True
            self.hand_machine.street = "preflop"
            self.hand_machine.board = []
            self.hand_machine.hero = []
            self.hand_machine.pot = None
            self.hand_state.update(active=True, id=self.hand_machine.hand_id, street="preflop",
                                   pot=None, boardCards=[], heroCards=[])
            self._start_action_timeline(
                self.hand_machine.hand_id, observed_at=boundary_at,
                frame_sequence=getattr(self, "latest_frame_sequence", 0),
                video_second=getattr(self, "recording_second", None))
            self.fields.commit("pot", None, 0, "dealer_boundary", True)
            self.fields.commit("minRaiseTo", None, 0, "dealer_boundary", True)
            self.fields.commit("preflopFullRaiseCount", None, 0, "dealer_boundary", True)
            self.decision_audit_snapshot = None
            self.hero_range_decision_snapshot = None
            self.prior_street_unresolved = None
            self.locked_hero_cards = []
            self.locked_hero_hand_id = self.hand_machine.hand_id
            self.hero_cards_present = False
            self.fast_hero_empty_frames = 0
            self.fast_board_candidate = []
            self.fast_board_frames = 0
            for field in ("heroCards", "boardCards"):
                self.card_candidates[field] = []
                self.card_candidate_frames[field] = 0
                self.card_published[field] = []
                self.card_visible[field] = []
                self.fields.commit(field, [], 1.0, "dealer_boundary", True)
            if previous_board:
                self.dealer_blocked_until_board_clear = True
                self.dealer_board_clear_since = None
            with self.state_lock:
                self.cached_state = dict(self.cached_state or {})
                self.cached_state.update(heroCards=[], boardCards=[], pot=None, minRaiseTo=None,
                                         preflopFullRaiseCount=None)
            self.hand_dealer_index = dealer_index
            self.hand_dealers[self.hand_machine.hand_id] = dealer_index
            cached_seats = list((self.cached_state or {}).get("seats") or [])
            self.history_store.observe_boundary(self.hand_machine.hand_id, dealer_index, cached_seats)
            self.hand_started_at = boundary_at if boundary_at is not None else time.time()
            recording_second = getattr(self, "recording_second", None)
            self.hand_started_second = (boundary_at if recording_second is not None and
                                        isinstance(boundary_at, (int, float)) and boundary_at < 1_000_000_000
                                        else recording_second)
            self.last_fast_hand_start_second = self.hand_started_second
            self.hand_boundary_confirmed = True
            self.force_slow_snapshot = True
            self.slow_refresh_event.set()
            self._action_event_ledger().close_projection()
            self.action_log.clear()
            self.folded_seats.clear()
            self.action_candidates.clear()
            self.fast_action_signatures.clear()
            self.reaction_estimate_cache_key = None
            self.reaction_estimate_cache = self._empty_reaction_estimates()
            self.previous_buttons.clear()
            self.visual_turn_detected = False
            self.hero_preselection = None
            self.hero_preselection_candidate = None
            self.hero_preselection_candidate_frame_sequence = None
            self.hero_preselection_candidate_frames = 0
            self.hero_preselection_clear_frames = 0
            self.hero_preselection_clear_frame_sequence = None
            self.action_button_preselection = None
            self.action_button_fragments = None
            self.visual_turn_hand_id = None
            self.visual_turn_street = None
            self.action_button_detected_at = None
            self.action_button_frame_captured_at = None
            self.hero_button_last_visible_frame_sequence = None
            self.hero_button_last_visible_hand_id = None
            self.hero_button_last_visible_street = None
            self.action_button_missing_frames = 0
            self.card_visible_frame_sequence = -1
            self.fast_hero_buttons = []
            self.pending_hero_buttons.clear()
            self.pending_hero_chips = None
            self.pending_hero_started = 0.0
            self.pending_hero_second = None
            self.pending_hero_frames = 0
            self.hero_last_official_buttons = []
            self.hero_last_official_second = None
            self.hero_button_release_context = None
            self.active_color_actions = {index: None for index in range(len(TABLE_LAYOUTS[self.layout]))}
            self.last_color_event_seat = None
            self.avatar_fold_frames = {index: 0 for index in range(len(TABLE_LAYOUTS[self.layout]))}
            self.avatar_contrast_history = {index: deque(maxlen=20) for index in range(len(TABLE_LAYOUTS[self.layout]))}
            self.hand_closed = False
            self.waiting_for_forced_bets = True
            self.forced_bet_seats = {}
            self.forced_bets_ready = False
            self.last_forced_straddle_probe = float("-inf")
            self.history_store.hand_profiles.clear()
            for tracker in self.seat_trackers.values():
                state_second = tracker.get("visualStateVideoSecond")
                state_observed_at = tracker.get("visualStateObservedAt")
                boundary_second = getattr(self, "recording_second", None)
                current_exclusion = (
                    tracker.get("visualState") in ("away", "waiting", "empty") and
                    ((boundary_second is not None and state_second is not None and
                      float(state_second) >= float(boundary_second) - .05) or
                     (boundary_second is None and boundary_at is not None and
                      state_observed_at is not None and
                      float(state_observed_at) >= float(boundary_at) - .05))
                )
                eligible = (tracker.get("occupancy") == "occupied" and
                            not current_exclusion)
                tracker.update(active=eligible, handEligible=eligible, lastAction="waiting",
                               stableBet=0.0, pendingBet=None, betFrames=0)
            self.hand_participants[self.hand_machine.hand_id] = {
                index for index, tracker in self.seat_trackers.items() if tracker.get("handEligible", True)
            }
            self.hand_player_counts[self.hand_machine.hand_id] = len(
                self.hand_participants[self.hand_machine.hand_id])
            previous_blinds = dict(self.blind_amounts)
            self.blind_amounts = previous_blinds
            small = self._next_tracker_seat(dealer_index)
            big = self._next_tracker_seat(small)
            self.formal_expected_seat = self._next_tracker_seat(big)
            self._set_forced_bet_seats(small, big, self.formal_expected_seat)
            forced_blinds = (
                (small, previous_blinds.get("small")),
                (big, previous_blinds.get("big")),
            )
            for seat_index, amount in forced_blinds:
                if not amount:
                    continue
                tracker = self.seat_trackers.get(seat_index, {})
                if tracker.get("occupancy") != "occupied" or not tracker.get("handEligible", True):
                    continue
                event = {"time": time.time(), "videoSecond": getattr(self, "recording_second", None),
                         "handId": self.hand_machine.hand_id, "street": "preflop", "sequence": 0,
                         "seat": seat_index + 1, "name": tracker.get("name", ""), "action": "blind",
                         "avatarHash": tracker.get("avatarHash", ""), "amount": amount, "increase": amount,
                         "chipsAfter": tracker.get("chips"), "potAfter": None, "confidence": .82,
                         "evidence": "庄家换位后按上一手盲注结构确认"}
                event["inferred"] = True
                event["observedAt"] = boundary_at or getattr(self, "latest_frame_captured_at", None)
                event["videoSecond"] = self.hand_started_second
                self._append_action_event(event)
            self._append_configured_forced_straddle(
                "牌桌盲注规则+庄家换位确认松浪盲注",
                observed_at=boundary_at)
            boundary = self.hand_started_second
            pending_forced = []
            for event in self.pending_hand_boundary_forced:
                observed = event.get("videoSecond")
                if boundary is None or observed is None or abs(observed - boundary) > 1.0:
                    continue
                promoted = dict(event)
                promoted.update(time=time.time(), handId=self.hand_machine.hand_id, street="preflop", sequence=0,
                                chainStatus="rule_confirmed" if event.get("amount") is not None else "amount_unresolved",
                                strategyEligible=event.get("amount") is not None)
                if event.get("amount") is None:
                    promoted["visualCandidate"] = True
                    self._append_action_candidate(promoted)
                else:
                    if self._append_action_event(promoted):
                        seat_index = (promoted.get("seat") or 1) - 1
                        tracker = self.seat_trackers.get(seat_index)
                        if tracker is not None:
                            tracker.update(stableBet=float(event["amount"]), pendingBet=None, betFrames=0)
                        self.formal_expected_seat = self._next_tracker_seat(seat_index)
                pending_forced.append(event)
            self.pending_hand_boundary_forced = [event for event in self.pending_hand_boundary_forced
                                                 if event not in pending_forced]
            return True

    def _complete_skipped_actions(self, observed_index, observed_at):
        expected = getattr(self, "formal_expected_seat", None)
        if expected is None or expected == observed_index:
            return []
        completed = []
        count = len(TABLE_LAYOUTS[self.layout])
        action = "fold" if self.hand_state.get("street") == "preflop" else "check"
        for _ in range(count):
            if expected == observed_index:
                break
            tracker = self.seat_trackers.get(expected)
            if tracker and tracker.get("occupancy") == "occupied" and tracker.get("lastAction") != "fold":
                recognized_at = time.time()
                event = {"time": recognized_at, "observedAt": observed_at,
                         "recognizedAt": recognized_at, "firstRecognizedAt": recognized_at,
                         "handId": self.hand_state.get("id"), "street": self.hand_state.get("street"),
                         "sequence": 1, "seat": expected + 1, "name": tracker.get("name", ""),
                         "action": action, "amount": tracker.get("stableBet", 0), "increase": 0,
                         "chipsAfter": tracker.get("chips"), "potAfter": None, "confidence": .7,
                         "evidence": "规则顺序补全（后位动作已确认）", "inferred": True}
                if self._append_action_event(event):
                    completed.append(event)
                    tracker["lastAction"] = action
            expected = self._next_tracker_seat(expected)
        self.formal_expected_seat = observed_index
        return completed

    def _advance_after_confirmed_straddle(self, seat_index, hand_id):
        if hand_id != self.hand_state.get("id"):
            return False
        voluntary = any(
            item.get("handId") == hand_id and item.get("street") == "preflop" and
            item.get("action") not in ("blind", "post_blind", "straddle")
            for item in self.action_log
        )
        if voluntary:
            return False
        self.formal_expected_seat = self._next_opponent_seat(seat_index)
        self.waiting_for_forced_bets = False
        return True

    def _append_configured_forced_straddle(self, evidence, observed_at=None, pot_after=None):
        hand_id = self.hand_state.get("id")
        if (not hand_id or self.hand_state.get("street") != "preflop" or
                not getattr(self, "waiting_for_forced_bets", False)):
            return None
        amount = self._effective_blind_straddle()
        small, big, straddle = self._current_forced_bet_seats()
        if amount is None or None in (small, big, straddle):
            return None
        tracker = self.seat_trackers.get(straddle, {})
        if tracker.get("occupancy") != "occupied" or not tracker.get("handEligible", True):
            return None
        current = [item for item in self.action_log
                   if item.get("handId") == hand_id and item.get("street") == "preflop"]
        confirmed_blinds = {item.get("seat") for item in current
                            if item.get("action") == "blind" and
                            item.get("amount") not in (None, 0)}
        if not {small + 1, big + 1}.issubset(confirmed_blinds):
            return None
        existing = next((item for item in current
                         if item.get("seat") == straddle + 1 and
                         item.get("action") == "straddle" and
                         item.get("amount") not in (None, 0)), None)
        if existing is not None:
            self._advance_after_confirmed_straddle(straddle, hand_id)
            return None
        if any(item.get("action") not in ("blind", "post_blind", "straddle")
               for item in current):
            return None
        event = {
            "time": time.time(), "observedAt": observed_at,
            "videoSecond": self.hand_started_second, "handId": hand_id,
            "street": "preflop", "sequence": 0, "seat": straddle + 1,
            "name": tracker.get("name", ""), "action": "straddle",
            "avatarHash": tracker.get("avatarHash", ""), "amount": float(amount),
            "increase": float(amount), "chipsAfter": tracker.get("chips"),
            "potAfter": pot_after, "confidence": .92, "inferred": True,
            "evidence": evidence,
        }
        if not self._append_action_event(event):
            return None
        tracker.update(lastAction="straddle", stableBet=float(amount),
                       pendingBet=None, betFrames=0)
        return event

    def _replace_same_frame_inferred_action(self, event):
        explicit_fold = bool(
            event.get("action") == "fold" and
            (event.get("evidenceSignals", {}).get("avatarText") or
             "avatar_text" in str(event.get("evidence") or "") or
             "明确弃牌文字" in str(event.get("evidence") or ""))
        )
        exact_amount_allin = bool(
            event.get("action") == "allin" and
            isinstance(event.get("amount"), (int, float)) and event.get("amount") > 0 and
            not event.get("inferred") and float(event.get("confidence") or 0) >= .55 and
            "allin_text+investment_amount" in str(event.get("evidence") or "") and
            "$" in str(event.get("investmentText") or "") and
            "." in str(event.get("investmentText") or "")
        )
        pending_lower_bound = next((
            item for item in reversed(self.action_log)
            if item.get("handId") == event.get("handId") and
            item.get("street") == event.get("street") and
            item.get("seat") == event.get("seat") and item.get("inferred") and
            item.get("pendingExactAmount") and item.get("amountLowerBound")
        ), None)
        explicit_pending_allin = bool(
            pending_lower_bound is not None and event.get("action") == "allin" and
            isinstance(event.get("amount"), (int, float)) and event.get("amount") > 0 and
            not event.get("inferred") and float(event.get("confidence") or 0) >= .55 and
            "avatar_allin_text" in str(event.get("evidence") or "")
        )
        if ((event.get("inferred") and not explicit_fold) or
                float(event.get("confidence") or 0) < ACTION_STRATEGY_CONFIDENCE and
                not exact_amount_allin and not explicit_pending_allin):
            return False
        event_frame = event.get("frameSequence")
        event_second = self._event_second(event)
        late_explicit_allin = bool(
            event.get("action") == "allin" and
            isinstance(event.get("amount"), (int, float)) and event.get("amount") > 0 and
            not event.get("inferred") and (
                float(event.get("confidence") or 0) >= .9 or exact_amount_allin or
                explicit_pending_allin
            )
        )
        prior = next((
            item for item in reversed(self.action_log)
            if item.get("handId") == event.get("handId") and
            item.get("street") == event.get("street") and
            item.get("seat") == event.get("seat") and item.get("inferred") and
            item.get("action") not in ("blind", "post_blind", "straddle") and
            item.get("action") != event.get("action") and (
             item is pending_lower_bound or
             ((event_frame is not None and item.get("frameSequence") == event_frame) or
             (event_second is not None and self._event_second(item) is not None and
              abs(float(event_second) - float(self._event_second(item))) <=
              (.5 if late_explicit_allin and item.get("action") in ("check", "fold") else .05)))
            )
        ), None)
        if prior is None:
            return False
        prior_index = self.action_log.index(prior)
        if any(
            item.get("handId") == event.get("handId") and
            item.get("street") == event.get("street") and
            item.get("action") not in ("blind", "post_blind", "straddle")
            for item in self.action_log[prior_index + 1:]
        ):
            return False
        self._action_event_ledger().sync_projection(
            self.action_log, "before_inferred_action_retraction")
        self.action_log.remove(prior)
        seat_index = event["seat"] - 1
        self.formal_expected_seat = seat_index
        if event.get("action") == "fold":
            retained = max((
                float(item.get("amount") or 0) for item in self.action_log
                if item.get("handId") == event.get("handId") and
                item.get("street") == event.get("street") and
                item.get("seat") == event.get("seat") and
                item.get("action") in ("blind", "post_blind", "straddle")
            ), default=0.0)
            event.update(amount=retained, increase=0.0,
                         evidence=f"{event.get('evidence') or 'explicit_action'}+same_frame_inference_replaced")
            tracker = self.seat_trackers.get(seat_index)
            if tracker is not None:
                tracker["stableBet"] = retained
        return True

    def _complete_rule_proven_postflop_checks(self, event):
        current = [item for item in self.action_log
                   if item.get("handId") == event.get("handId") and
                   item.get("street") == event.get("street")]
        terminal = {seat - 1 for seat in self.folded_seats}
        terminal.update((item.get("seat") or 1) - 1 for item in self.action_log
                        if item.get("handId") == self.hand_state.get("id") and
                        item.get("action") in ("fold", "allin"))
        selected = ActionEngine.select_rule_proven_checks(
            event, self.action_log, self.seat_trackers,
            self.formal_expected_seat, len(TABLE_LAYOUTS[self.layout]),
            self._current_hand_eligible_indices(), terminal)
        repaired = []
        for expected in selected:
            tracker = self.seat_trackers.get(expected, {})
            existing = next((item for item in current
                             if item.get("seat") == expected + 1 and
                             item.get("action") == "check"), None)
            if existing is not None:
                existing.update(orderConflict=False, strategyEligible=True,
                                chainStatus="rule_confirmed",
                                confidence=max(.9, float(existing.get("confidence") or 0)),
                                evidence=f"{existing.get('evidence') or 'check'}+later_action_order_confirmed")
                self.formal_expected_seat = self._next_opponent_seat(expected)
                repaired.append(existing)
                continue
            check = {
                "time": time.time(), "observedAt": event.get("observedAt"),
                "recognizedAt": time.time(), "frameSequence": event.get("frameSequence"),
                "videoSecond": event.get("videoSecond"), "handId": event.get("handId"),
                "street": event.get("street"), "sequence": 1, "seat": expected + 1,
                "name": tracker.get("name", ""),
                "action": "check", "amount": 0.0, "increase": 0.0,
                "confidence": .9, "inferred": True, "chainStatus": "rule_confirmed",
                "strategyEligible": True,
                "evidence": "later_explicit_action+no_prior_bet_rule_confirmed_check",
            }
            if not self._append_action_event(check, resolve_prior=False):
                break
            repaired.append(check)
        return repaired

    def _advance_formal_actor(self, observed_index, action):
        if action in ("bet", "raise", "reraise"):
            self.formal_expected_seat = self._next_tracker_seat(observed_index)

    def _promote_prior_fold_candidates(self, observed_index):
        expected = getattr(self, "formal_expected_seat", None)
        if expected is None or expected == observed_index:
            return
        selection = ActionEngine.select_fold_promotions(
            self.action_candidates, self.hand_state.get("id"),
            self.hand_state.get("street"), expected,
            len(TABLE_LAYOUTS[self.layout]), self._current_hand_eligible_indices(),
            stop_before=observed_index)
        for candidate in selection["candidates"]:
            promoted = dict(candidate)
            promoted.pop("visualCandidate", None)
            promoted.update(chainStatus="rule_confirmed", strategyEligible=True, confidence=.88,
                            evidence="fold_visual_candidate+later_action_order", inferred=True)
            if self._append_action_event(promoted, resolve_prior=False):
                candidate["promoted"] = True
                tracker = self.seat_trackers.get((candidate.get("seat") or 1) - 1)
                if tracker:
                    tracker["lastAction"] = "fold"

    def _update_action_state_locked(self, seats, reset=False, pot_after=None):
        events = []
        if getattr(self, "hand_closed", False) and not reset:
            for seat in seats:
                tracker = self.seat_trackers.get(seat["index"], {})
                seat["streetBet"] = tracker.get("stableBet", 0.0)
                seat["action"] = tracker.get("lastAction", "waiting")
                seat["diagnostic"] = {"seat": seat["index"] + 1, "status": tracker.get("occupancy", "occupied"),
                                      "previousBet": tracker.get("stableBet", 0.0), "currentBet": seat.get("streetBet"),
                                      "action": seat["action"], "confidence": .9, "evidence": "本手已结束，停止记录"}
            return seats, events
        if reset:
            for tracker in self.seat_trackers.values():
                tracker.update(active=tracker["occupancy"] == "occupied", lastAction="waiting",
                               stableBet=0.0, pendingBet=None, betFrames=0)
        previous_highest = max((tracker["stableBet"] for tracker in self.seat_trackers.values()), default=0.0)
        blind_amounts = getattr(self, "blind_amounts", {})
        dealer = getattr(self, "hand_dealer_index", None)
        small_blind = self._next_tracker_seat(dealer) if dealer is not None else None
        big_blind = self._next_tracker_seat(small_blind) if small_blind is not None else None
        straddle_seat = (self._next_tracker_seat(big_blind) if big_blind is not None and
                         self._straddle_allowed_for_hand(seats) else None)
        frame_big_blind = next((float(seat.get("streetBet")) for seat in seats
                                if seat.get("index") == big_blind and
                                seat.get("streetBet") is not None and
                                float(seat.get("streetBet")) > 0), 0.0)
        hero_index = 4 if self.layout == "8max" else 3
        for seat in seats:
            tracker = self.seat_trackers[seat["index"]]
            observed_bet = seat.get("streetBet")
            previous_bet = tracker["stableBet"]
            action, confidence, evidence = tracker["lastAction"], .45, "金额未稳定"
            direct_action = seat.get("action")
            folded_this_hand = any(
                item.get("handId") == self.hand_state.get("id") and
                item.get("seat") == seat["index"] + 1 and
                item.get("action") == "fold"
                for item in self.action_log
            )
            if folded_this_hand:
                tracker["lastAction"] = "fold"
                direct_action = "waiting"
            blind_count = sum(item.get("handId") == self.hand_state.get("id") and item.get("action") == "blind" for item in self.action_log)
            if getattr(self, "waiting_for_forced_bets", False) and blind_count < 2 and direct_action == "fold":
                direct_action = "waiting"
            if (seat.get("isHero") or seat.get("index") == hero_index) and \
                    direct_action not in ("blind", "post_blind", "straddle"):
                direct_action = "waiting"
            explicit_direct_action = direct_action
            if seat.get("index") == hero_index and direct_action == "waiting":
                observed_bet = None
            if direct_action in ("fold", "check") and direct_action != tracker["lastAction"]:
                action, confidence, evidence = direct_action, .88, "座位状态文字或灰化"
                event = {"time": seat.get("recognizedAt") or time.time(),
                         "recognizedAt": seat.get("recognizedAt"),
                         "queueLatencyMs": seat.get("queueLatencyMs"),
                         "ocrDurationMs": seat.get("ocrDurationMs"),
                         "handId": self.hand_state["id"], "street": self.hand_state["street"],
                         "observedAt": seat.get("observedAt"), "frameSequence": seat.get("frameSequence"),
                         "sequence": 1 + sum(item.get("street") == self.hand_state["street"] and item.get("action") not in ("blind", "post_blind")
                                             for item in self.action_log),
                         "seat": seat["index"] + 1, "name": seat.get("name", ""), "action": direct_action,
                         "avatarHash": seat.get("avatarHash", ""),
                         "amount": 0.0 if direct_action == "check" else tracker["stableBet"],
                         "increase": 0, "chipsAfter": seat.get("chips"),
                         "potAfter": pot_after, "confidence": confidence, "evidence": evidence}
                if self._append_action_event(event):
                    tracker["lastAction"] = direct_action
                    events.append(event)
            if observed_bet is not None:
                observed_bet = float(observed_bet)
                opening_straddle = False
                recorded_blind = next((item for item in reversed(self.action_log)
                                       if item.get("handId") == self.hand_state["id"] and
                                       item.get("street") == "preflop" and
                                       item.get("seat") == seat["index"] + 1 and
                                       item.get("action") == "blind"), None)
                if (recorded_blind and tracker["stableBet"] <= .01 and
                        abs(observed_bet - float(recorded_blind.get("amount") or 0)) <= .01):
                    tracker.update(stableBet=observed_bet, pendingBet=None, betFrames=0)
                    seat["streetBet"] = observed_bet
                    seat["action"] = tracker["lastAction"]
                    seat["diagnostic"] = {
                        "seat": seat["index"] + 1, "status": tracker["occupancy"],
                        "previousBet": previous_bet, "currentBet": observed_bet,
                        "action": tracker["lastAction"], "confidence": .95,
                        "evidence": "已记录盲注同步至座位累计投入",
                    }
                    continue
                recorded_big_blind = next((float(item.get("amount") or 0) for item in reversed(self.action_log)
                                           if item.get("handId") == self.hand_state["id"] and
                                           item.get("street") == "preflop" and
                                           item.get("seat") == (big_blind + 1 if big_blind is not None else None) and
                                           item.get("action") == "blind"),
                                          float(blind_amounts.get("big") or 0))
                observed_text = str(seat.get("investmentText") or "")
                if (recorded_blind and "." not in observed_text and
                        any(abs(observed_bet - float(recorded_blind.get("amount") or 0) * scale) <= .01
                            for scale in (10, 100))):
                    observed_bet = float(recorded_blind.get("amount") or 0)
                current_second = getattr(self, "recording_second", None)
                near_hand_start = (current_second is not None and self.hand_started_second is not None and
                                   0 <= current_second - self.hand_started_second <= 1.5)
                voluntary_exists = any(item.get("handId") == self.hand_state["id"] and
                                       item.get("action") not in ("blind", "post_blind", "straddle")
                                       for item in self.action_log)
                opening_big_blind_double_without_text = (
                    self.hand_state["street"] == "preflop" and
                    getattr(self, "waiting_for_forced_bets", False) and
                    not voluntary_exists and
                    seat["index"] == big_blind and
                    direct_action == "waiting" and
                    recorded_blind is not None and
                    tracker["stableBet"] <= float(recorded_blind.get("amount") or 0) + .01 and
                    not observed_text and
                    abs(observed_bet - float(recorded_blind.get("amount") or 0) * 2) <= .01
                )
                if opening_big_blind_double_without_text:
                    tracker["stableBet"] = max(
                        tracker.get("stableBet", 0.0),
                        float(recorded_blind.get("amount") or 0),
                    )
                    tracker["pendingBet"] = None
                    tracker["pendingBetText"] = ""
                    tracker["betFrames"] = 0
                    seat["streetBet"] = tracker["stableBet"]
                    seat["action"] = tracker["lastAction"]
                    continue
                premature_blind_rebet = (recorded_blind is not None and
                                         getattr(self, "waiting_for_forced_bets", False) and
                                         not voluntary_exists and
                                         seat["index"] != getattr(self, "formal_expected_seat", None) and
                                         observed_bet > float(recorded_blind.get("amount") or 0) + .01)
                if premature_blind_rebet:
                    tracker["pendingBet"] = None
                    tracker["pendingBetText"] = ""
                    tracker["betFrames"] = 0
                    seat["streetBet"] = tracker["stableBet"]
                    seat["action"] = tracker["lastAction"]
                    continue
                if (self.hand_state["street"] == "preflop" and near_hand_start and not voluntary_exists and
                        big_blind is not None and seat["index"] == self._next_tracker_seat(big_blind) and
                        direct_action == "straddle" and tracker["stableBet"] <= .01):
                    opening_straddle = True
                amount_plausible = observed_bet <= 50 if pot_after is None else observed_bet <= max(pot_after * 1.5, 20)
                voluntary_started = any(item.get("handId") == self.hand_state.get("id") and
                                        item.get("action") not in ("blind", "post_blind", "straddle")
                                        for item in self.action_log)
                if (self.hand_state["street"] == "preflop" and direct_action == "post_blind" and tracker["stableBet"] <= .01 and
                      abs(observed_bet - (blind_amounts.get("big") or 0)) <= .01 and
                      seat["index"] not in (small_blind, big_blind) and not voluntary_started):
                    direct_action = "post_blind"
                elif (direct_action not in ("post_blind", "straddle", "call", "bet", "raise") and
                        not opening_straddle and amount_plausible and
                        self.hand_state["street"] == "preflop" and tracker["stableBet"] <= .01 and
                        observed_bet > (blind_amounts.get("big") or 0) + .01 and
                        seat["index"] not in (small_blind, big_blind)):
                    direct_action = "raise"
                if not amount_plausible:
                    direct_action = "waiting"
                    observed_bet = tracker["stableBet"]
                if observed_bet <= tracker["stableBet"] + .01:
                    tracker["pendingBet"] = None
                    tracker["betFrames"] = 0
                    seat["streetBet"] = tracker["stableBet"]
                    seat["action"] = tracker["lastAction"]
                    seat["diagnostic"] = {
                        "seat": seat["index"] + 1, "status": tracker["occupancy"],
                        "previousBet": previous_bet, "currentBet": observed_bet,
                        "action": tracker["lastAction"], "confidence": .9,
                        "evidence": "累计投入未变化",
                    }
                    continue
                pending_text = str(tracker.get("pendingBetText") or "")
                stable_decimal_wins = (tracker["stableBet"] > 0 and
                                       not observed_text and
                                       abs(observed_bet - tracker["stableBet"] * 10) <= .01)
                if stable_decimal_wins:
                    observed_bet = float(tracker["stableBet"])
                decimal_candidate_wins = (tracker["pendingBet"] not in (None, 0) and
                                          "." in pending_text and "." not in observed_text and
                                          observed_bet >= float(tracker["pendingBet"]) * 10)
                if decimal_candidate_wins:
                    observed_bet = float(tracker["pendingBet"])
                if tracker["pendingBet"] is not None and abs(tracker["pendingBet"] - observed_bet) < .01:
                    tracker["betFrames"] += 1
                else:
                    tracker["pendingBet"], tracker["betFrames"] = observed_bet, 1
                    tracker["pendingBetText"] = observed_text
                clear_forced_blind = (getattr(self, "waiting_for_forced_bets", False) and
                                      seat["index"] in (small_blind, big_blind) and
                                      "$" in str(seat.get("investmentText") or "") and
                                      "." in str(seat.get("investmentText") or ""))
                known_big = float(recorded_big_blind or blind_amounts.get("big") or 0)
                if (direct_action == "straddle" and known_big > 0 and "." not in observed_text and
                        abs(observed_bet - known_big * 20) <= max(.01, known_big * .2)):
                    observed_bet = round(known_big * 2, 4)
                    tracker["pendingBet"] = observed_bet
                    tracker["pendingBetText"] = observed_text
                clear_straddle = (direct_action == "straddle" and
                                  (("$" in observed_text and "." in observed_text) or
                                   (known_big > 0 and
                                    abs(observed_bet - known_big * 2) <= max(.01, known_big * .12))))
                implausible_straddle = (direct_action == "straddle" and known_big > 0 and
                                        not clear_straddle and
                                        observed_bet > known_big * 5 and
                                        "$" not in observed_text and "." not in observed_text)
                if implausible_straddle:
                    tracker["pendingBet"] = None
                    tracker["betFrames"] = 0
                    continue
                required_frames = 1 if (clear_forced_blind or clear_straddle or direct_action in (
                    "post_blind", "bet", "call", "raise")) else 2
                other_highest = max((value.get("stableBet", 0.0) for key, value in self.seat_trackers.items()
                                     if key != seat["index"]), default=0.0)
                if (direct_action == "waiting" and observed_bet > tracker["stableBet"] + .01 and
                        other_highest > 0 and abs(observed_bet - other_highest) <= .01):
                    direct_action = "call"
                    required_frames = 1
                if tracker["betFrames"] >= required_frames and abs(observed_bet - tracker["stableBet"]) >= .01:
                    old = tracker["stableBet"]
                    if observed_bet > old:
                        current_hand_events = [event for event in self.action_log
                                               if event.get("handId") == self.hand_state["id"]]
                        current_big_blind = max(
                            (float(event.get("amount") or 0) for event in current_hand_events
                             if event.get("street") == "preflop" and event.get("action") == "blind"),
                            default=float(blind_amounts.get("big") or 0))
                        inferred_opening_straddle = False
                        straddle_already_recorded = any(
                            item.get("handId") == self.hand_state["id"] and
                            item.get("street") == "preflop" and
                            item.get("seat") == seat["index"] + 1 and
                            item.get("action") == "straddle"
                            for item in self.action_log)
                        if direct_action == "straddle" and straddle_already_recorded:
                            tracker["pendingBet"] = None
                            tracker["pendingBetText"] = ""
                            tracker["betFrames"] = 0
                            continue
                        blind_already_recorded = any(item.get("handId") == self.hand_state["id"] and
                                                     item.get("street") == "preflop" and
                                                     item.get("seat") == seat["index"] + 1 and
                                                     item.get("action") == "blind"
                                                     for item in self.action_log)
                        if (self.hand_state["street"] == "preflop" and old <= .01 and
                                getattr(self, "waiting_for_forced_bets", False) and
                                not voluntary_exists and not blind_already_recorded and
                                seat["index"] in (small_blind, big_blind)):
                            action = "blind"
                            role = "small" if seat["index"] == small_blind else "big"
                            known_blind = float(blind_amounts.get(role) or 0)
                            if role == "small" and frame_big_blind > 0 and observed_bet > frame_big_blind * 5:
                                observed_bet = round(frame_big_blind * .4, 4)
                            elif known_blind > 0 and observed_bet > known_blind * 5:
                                observed_bet = known_blind
                        elif self.hand_state["street"] == "preflop" and (
                                direct_action == "straddle" or opening_straddle or inferred_opening_straddle):
                            action = "straddle"
                        elif self.hand_state["street"] == "preflop" and direct_action == "post_blind":
                            action = "post_blind"
                        elif direct_action == "call":
                            action = "call"
                        elif observed_bet <= previous_highest + .01 and previous_highest > 0:
                            action = "call"
                        elif (self.hand_state["street"] == "preflop" and
                              observed_bet > previous_highest + .01 and
                              any(event.get("handId") == self.hand_state["id"] and
                                  event.get("street") == "preflop" and
                                  event.get("action") in ("blind", "post_blind", "straddle")
                                  for event in self.action_log)):
                            action = "raise"
                        elif not any(event.get("handId") == self.hand_state["id"] and
                                     event.get("street") == self.hand_state["street"] and
                                     event.get("action") in ("bet", "raise", "reraise", "call", "allin")
                                     for event in self.action_log):
                            action = "bet"
                        elif observed_bet > previous_highest + .01:
                            action = "reraise" if any(
                                event.get("handId") == self.hand_state["id"] and
                                event.get("street") == self.hand_state["street"] and
                                event.get("action") in ("raise", "reraise")
                                for event in self.action_log) else "raise"
                        else:
                            action = "call"
                        confirmed_call = (
                            action == "call" and explicit_direct_action == "call" and previous_highest > 0 and
                            abs(observed_bet - previous_highest) <= .01 and
                            seat["index"] == getattr(self, "formal_expected_seat", None)
                        )
                        confidence = .9 if confirmed_call else .85
                        evidence = (f"明确跟注至已确认最高投入 {observed_bet:g}" if confirmed_call else
                                    f"下注 {old:g}→{observed_bet:g}")
                        sequence = 0 if action in ("blind", "post_blind", "straddle") else 1 + sum(
                            item.get("street") == self.hand_state["street"] and item.get("action") not in ("blind", "post_blind", "straddle")
                            for item in self.action_log)
                        event = {"time": time.time(), "handId": self.hand_state["id"], "street": self.hand_state["street"],
                                 "videoSecond": seat.get("videoSecond", getattr(self, "recording_second", None)),
                                 "observedAt": seat.get("observedAt"), "frameSequence": seat.get("frameSequence"),
                                 "sequence": sequence,
                                 "seat": seat["index"] + 1, "name": seat.get("name", ""), "action": action,
                                 "avatarHash": seat.get("avatarHash", ""),
                                 "amount": observed_bet, "increase": observed_bet - old,
                                 "chipsAfter": seat.get("chips"), "potAfter": pot_after,
                                 "confidence": confidence, "evidence": evidence,
                                 "investmentText": seat.get("investmentText", ""),
                                 "capsuleEpoch": seat.get("capsuleEpoch"),
                                 "evidenceSource": seat.get("evidenceSource"),
                                 "recognizedAt": seat.get("recognizedAt"),
                                 "queueLatencyMs": seat.get("queueLatencyMs"),
                                 "ocrDurationMs": seat.get("ocrDurationMs")}
                        accepted = self._append_action_event(event)
                        if accepted:
                            tracker["stableBet"] = event.get("amount", observed_bet)
                            tracker["lastAction"] = event.get("action", action)
                            events.append(event)
                            if action == "blind" and seat["index"] == big_blind and observed_bet > 0:
                                prior_small_event = next((item for item in reversed(self.action_log)
                                                          if item.get("handId") == self.hand_state["id"] and
                                                          item.get("street") == "preflop" and
                                                          item.get("seat") == small_blind + 1 and
                                                          item.get("action") == "blind"), None)
                                if (prior_small_event and
                                        float(prior_small_event.get("amount") or 0) >= observed_bet):
                                    corrected_small = round(observed_bet * .4, 4)
                                    prior_small_event.update(amount=corrected_small, increase=corrected_small,
                                                             evidence=f"{prior_small_event.get('evidence', '')}+大小盲结构校正")
                                    small_tracker = self.seat_trackers.get(small_blind)
                                    if small_tracker is not None:
                                        small_tracker["stableBet"] = corrected_small
                        tracker["pendingBet"] = None
                        tracker["pendingBetText"] = ""
                        tracker["betFrames"] = 0
                        if accepted and action == "blind":
                            if seat["index"] == small_blind:
                                self.blind_amounts["small"] = observed_bet
                            elif seat["index"] == big_blind:
                                self.blind_amounts["big"] = observed_bet
                        if accepted and action == "straddle":
                            self.formal_expected_seat = self._next_tracker_seat(seat["index"])
                        if accepted and action not in ("blind", "post_blind", "straddle"):
                            self.waiting_for_forced_bets = False
                        previous_highest = max(previous_highest, observed_bet)
            seat["streetBet"] = tracker["stableBet"]
            seat["action"] = tracker["lastAction"]
            seat["diagnostic"] = {"seat": seat["index"] + 1, "status": tracker["occupancy"], "previousBet": previous_bet, "currentBet": observed_bet, "action": action, "confidence": confidence, "evidence": evidence}
        for event in events:
            active = [tracker for tracker in self.seat_trackers.values() if tracker.get("occupancy") == "occupied"]
            event["playersActive"] = sum(tracker.get("lastAction") != "fold" for tracker in active)
            event["unactedAfter"] = sum(tracker.get("lastAction") == "waiting" for tracker in active)
        return seats, events

    def _normalize_forced_amount(self, event):
        if event.get("action") != "post_blind" or event.get("street") != "preflop":
            return True
        amount = event.get("amount")
        if not isinstance(amount, (int, float)) or amount <= 0:
            return True
        forced_amounts = [
            float(item.get("amount") or 0)
            for item in self.action_log
            if item.get("handId") == event.get("handId") and
            item.get("street") == "preflop" and
            item.get("action") in ("blind", "post_blind", "straddle") and
            isinstance(item.get("amount"), (int, float)) and item.get("amount") > 0
        ]
        big_blind = float(getattr(self, "blind_amounts", {}).get("big") or 0)
        live_forced = max(forced_amounts + [big_blind], default=0.0)
        if live_forced <= 0 or float(amount) <= live_forced * 4 + .001:
            return True
        known_forced = sorted(set(forced_amounts + ([big_blind] if big_blind > 0 else [])))
        for divisor in (10, 100):
            corrected = round(float(amount) / divisor, 6)
            if any(abs(corrected - known) <= max(.001, known * .08)
                   for known in known_forced):
                event["amount"] = corrected
                event["increase"] = corrected
                event["evidence"] = f"{event.get('evidence', '')}+forced_amount_decimal_recovered"
                return True
        return False

    def _append_action_event(self, event, resolve_prior=True):
        if event.get("runtimeId") is not None and event.get("runtimeId") != self.runtime_id:
            return False
        if (event.get("tableSession") is not None and
                event.get("tableSession") != self.table_session):
            return False
        current_hand = self.hand_state.get("id")
        if (self.hand_state.get("active") and current_hand and
                event.get("handId") is not None and event.get("handId") != current_hand):
            return False
        actor_tracker = self.seat_trackers.get((event.get("seat") or 1) - 1, {})
        if (actor_tracker.get("joinedDuringHandId") == event.get("handId") and
                (event.get("seat") or 1) - 1 not in
                self.hand_participants.get(event.get("handId"), set())):
            return False
        pending_aggressive_correction = None
        if getattr(self, "recording_second", None) is not None and event.get("observedAt") is not None:
            event["videoSecond"] = event["observedAt"]
        if event.get("action") == "straddle" and not self._straddle_allowed_for_hand():
            return False
        if not self._normalize_forced_amount(event):
            return False
        if (event.get("action") in ("call", "bet", "raise", "reraise", "allin") and
                event.get("amount") not in (None, 0) and
                isinstance(event.get("chipsBefore"), (int, float))):
            prior_invested = max(
                (float(item.get("amount") or 0) for item in self.action_log
                 if item.get("handId") == event.get("handId") and
                 item.get("street") == event.get("street") and
                 item.get("seat") == event.get("seat") and
                 item.get("action") in ("blind", "post_blind", "straddle", "call",
                                        "bet", "raise", "reraise", "allin")),
                default=0.0,
            )
            maximum_total = prior_invested + max(0.0, float(event["chipsBefore"]))
            if float(event["amount"]) > maximum_total + max(.01, maximum_total * .03):
                return False
        if event.get("action") == "straddle" and event.get("street") == "preflop":
            _, _, straddle_index = self._current_forced_bet_seats()
            event_second = self._event_second(event)
            prior = next((item for item in reversed(self.action_log)
                          if item.get("handId") == event.get("handId") and
                          item.get("street") == "preflop" and
                          item.get("seat") == event.get("seat") and
                          item.get("action") in ("call", "bet", "raise") and
                          (event_second is None or self._event_second(item) is None or
                           0 <= float(event_second) - float(self._event_second(item)) <= 1.0)), None)
            intervening = bool(prior and any(
                item.get("handId") == event.get("handId") and
                item.get("street") == "preflop" and item.get("seat") != event.get("seat") and
                item.get("action") not in ("blind", "post_blind", "straddle")
                for item in self.action_log[self.action_log.index(prior) + 1:]
            ))
            if (prior is not None and event.get("seat") ==
                    (straddle_index + 1 if straddle_index is not None else None) and
                    event.get("amount") not in (None, 0) and not intervening):
                prior.update(
                    action="straddle", amount=float(event["amount"]),
                    increase=float(event["amount"]), sequence=0,
                    confidence=max(float(prior.get("confidence") or 0),
                                   float(event.get("confidence") or 0)),
                    evidence=f"{prior.get('evidence') or 'investment'}+explicit_straddle_reclassified",
                    investmentText=event.get("investmentText", ""),
                    chainStatus="direct_confirmed", strategyEligible=True,
                    orderConflict=False,
                )
                tracker = self.seat_trackers.get(event["seat"] - 1)
                if tracker is not None:
                    tracker.update(lastAction="straddle", stableBet=float(event["amount"]))
                self._advance_after_confirmed_straddle(event["seat"] - 1, event.get("handId"))
                return False

        self._confirm_prior_street_check(event)
        self._confirm_hero_check_before_next_action(event)
        if event.get("action") == "fold" and event.get("seat") in self.folded_seats:
            return False
        if ActionLedgerLayer.has_confirmed_terminal(self.action_log, event):
            return False
        inferred_official_fold = next((
            item for item in reversed(self.action_log)
            if item.get("handId") == event.get("handId") and
            item.get("street") == event.get("street") and
            item.get("seat") == event.get("seat") and
            item.get("action") == "fold" and item.get("inferred") and
            str(item.get("evidence") or "").startswith("official_hero_turn+")
        ), None)
        if inferred_official_fold is not None and event.get("action") != "fold":
            fold_observed = inferred_official_fold.get(
                "observedAt", inferred_official_fold.get("videoSecond"))
            event_observed = event.get("observedAt", event.get("videoSecond"))
            if (fold_observed is None or event_observed is None or
                    float(event_observed) >= float(fold_observed)):
                return False
        if (resolve_prior and event.get("seat") and
                event.get("action") not in ("blind", "post_blind", "straddle", "fold") and
                self.formal_expected_seat != event.get("seat") - 1):
            self._promote_prior_fold_candidates(event["seat"] - 1)
        if resolve_prior:
            self._complete_rule_proven_postflop_checks(event)
        if (getattr(self, "waiting_for_forced_bets", False) and
                event.get("action") not in ("blind", "post_blind", "straddle") and
                event.get("seat") != (self.formal_expected_seat + 1
                                      if self.formal_expected_seat is not None else None)):
            return False
        if getattr(self, "waiting_for_forced_bets", False) and event.get("action") == "call":
            forced_highest = max((float(item.get("amount") or 0) for item in self.action_log
                                  if item.get("handId") == event.get("handId") and
                                  item.get("street") == "preflop" and
                                  item.get("action") in ("blind", "post_blind", "straddle")),
                                 default=0.0)
            if (forced_highest <= 0 or event.get("amount") in (None, 0) or
                    abs(float(event["amount"]) - forced_highest) > max(.001, forced_highest * .08)):
                return False
        if event.get("action") == "post_blind":
            prior = next((item for item in reversed(self.action_log)
                          if item.get("handId") == event.get("handId") and
                          item.get("street") == "preflop" and
                          item.get("seat") == event.get("seat") and
                          item.get("action") in ("call", "bet", "raise") and
                          abs(float(item.get("observedAt") or item.get("videoSecond") or 0) -
                              float(event.get("observedAt") or event.get("videoSecond") or 0)) <= 1.0), None)
            if prior is not None:
                override_key = (event.get("handId"), event.get("street"), event.get("seat"),
                                round(float(prior.get("observedAt") or prior.get("videoSecond") or 0), 3))
                self.forced_action_overrides[override_key] = "post_blind"
                prior.update(action="post_blind", sequence=0,
                             evidence=f"{prior.get('evidence', '')}+补盲文字覆盖金额推断",
                             confidence=max(float(prior.get("confidence") or 0),
                                            float(event.get("confidence") or 0)))
                event_amount = event.get("amount")
                prior_amount = prior.get("amount")
                if (event_amount not in (None, 0) and prior_amount not in (None, 0) and
                        float(event_amount) < float(prior_amount)):
                    prior.update(amount=event_amount, increase=event_amount)
                tracker = self.seat_trackers.get((event.get("seat") or 1) - 1)
                if tracker is not None:
                    tracker.update(lastAction="post_blind", stableBet=prior.get("amount", 0))
                return False
        if event.get("action") == "call":
            call_amount = event.get("amount")
            call_text = str(event.get("investmentText") or "")
            event_second = event.get("observedAt", event.get("videoSecond"))
            def occurred_before(item):
                item_second = item.get("observedAt", item.get("videoSecond"))
                return (event_second is None or item_second is None or
                        float(item_second) <= float(event_second) + .3)
            latest_aggressive = next((item for item in reversed(self.action_log)
                                      if item.get("handId") == event.get("handId") and
                                      item.get("street") == event.get("street") and
                                      item.get("seat") != event.get("seat") and
                                      item.get("action") in ("bet", "raise", "reraise", "allin") and
                                      occurred_before(item)), None)
            actor_invested = max(
                float(self.seat_trackers.get((event.get("seat") or 1) - 1, {}).get("stableBet") or 0),
                max((float(item.get("amount") or 0) for item in self.action_log
                     if item.get("handId") == event.get("handId") and
                     item.get("street") == event.get("street") and
                     item.get("seat") == event.get("seat") and
                     item.get("action") in ("blind", "post_blind", "straddle", "call",
                                            "bet", "raise", "reraise", "allin")), default=0.0),
            )
            aggressive_amount = float(latest_aggressive.get("amount") or 0) if latest_aggressive else 0.0
            amount_tolerance = max(.01, aggressive_amount * .02)
            if (call_amount not in (None, 0) and actor_invested > 0 and aggressive_amount > 0 and
                    abs(actor_invested + float(call_amount) - aggressive_amount) <= amount_tolerance):
                event["amount"] = aggressive_amount
                event["increase"] = max(0.0, aggressive_amount - actor_invested)
                event["evidence"] = f"{event.get('evidence', '')}+displayed_increment_to_call_price"
                call_amount = aggressive_amount
            if (latest_aggressive is not None and call_amount not in (None, 0) and
                    "." in call_text and latest_aggressive.get("amount") not in (None, 0) and
                    abs(float(latest_aggressive["amount"]) - float(call_amount)) >
                    max(.01, float(call_amount) * .08)):
                later_aggressive = any(item.get("handId") == event.get("handId") and
                                       item.get("street") == event.get("street") and
                                       item.get("action") in ("raise", "reraise", "allin")
                                       for item in self.action_log[self.action_log.index(latest_aggressive) + 1:])
                if not later_aggressive:
                    previous_amount = float(latest_aggressive["amount"])
                    previous_increase = latest_aggressive.get("increase")
                    pending_aggressive_correction = {
                        "event": latest_aggressive,
                        "amount": float(call_amount),
                        "investmentText": call_text,
                        "evidence": f"{latest_aggressive.get('evidence', '')}+call_amount_cross_checked",
                        "increase": (float(call_amount) if previous_increase is not None and
                                     abs(float(previous_increase) - previous_amount) <= .01 else
                                     previous_increase),
                    }
            confirmed_highest = max((float(item.get("amount") or 0) for item in self.action_log
                                     if item.get("handId") == event.get("handId") and
                                     item.get("street") == event.get("street") and
                                     item.get("seat") != event.get("seat") and
                                     item.get("action") in ("blind", "post_blind", "straddle",
                                                            "bet", "raise", "reraise", "allin") and
                                     occurred_before(item) and
                                     item is not (pending_aggressive_correction or {}).get("event")),
                                    default=0.0)
            if pending_aggressive_correction is not None:
                confirmed_highest = max(
                    confirmed_highest, pending_aggressive_correction["amount"])
            if confirmed_highest and (event.get("amount") in (None, 0) or
                                      abs(float(event["amount"]) - confirmed_highest) >
                                      max(.01, confirmed_highest * .08)):
                event["amount"] = confirmed_highest
                event["increase"] = max(0.0, confirmed_highest - actor_invested)
                event["evidence"] = f"{event.get('evidence', '')}+call_amount_rule_checked"
        if event.get("action") in ("bet", "raise", "reraise") and event.get("amount") not in (None, 0):
            prior_street = [item for item in self.action_log
                            if item.get("handId") == event.get("handId") and
                            item.get("street") == event.get("street") and
                            item.get("seat") != event.get("seat")]
            prior_highest = max((float(item.get("amount") or 0) for item in prior_street
                                 if item.get("action") in ("blind", "post_blind", "straddle",
                                                           "bet", "raise", "reraise", "allin")),
                                default=0.0)
            prior_raise = any(item.get("action") in ("raise", "reraise", "allin")
                              for item in prior_street)
            if float(event["amount"]) > prior_highest + .01:
                if prior_raise:
                    event["action"] = "reraise"
                elif event.get("street") == "preflop" and prior_highest > 0:
                    event["action"] = "raise"
                elif event.get("street") != "preflop" and prior_highest <= 0:
                    event["action"] = "bet"
                if ("明确动作文字+货币金额" in str(event.get("evidence") or "") and
                        "$" in str(event.get("investmentText") or "") and
                        "." in str(event.get("investmentText") or "")):
                    event["confidence"] = max(.9, float(event.get("confidence") or 0))
            else:
                actor_invested = max(
                    float(self.seat_trackers.get((event.get("seat") or 1) - 1, {}).get("stableBet") or 0),
                    max((float(item.get("amount") or 0) for item in self.action_log
                         if item.get("handId") == event.get("handId") and
                         item.get("street") == event.get("street") and
                         item.get("seat") == event.get("seat") and
                         item.get("action") in ("blind", "post_blind", "straddle", "call",
                                                "bet", "raise", "reraise", "allin")), default=0.0),
                )
                tolerance = max(.01, prior_highest * .02)
                displayed_amount = float(event["amount"])
                if abs(displayed_amount - prior_highest) <= tolerance:
                    event["action"] = "call"
                    event["amount"] = prior_highest
                    event["increase"] = max(0.0, prior_highest - actor_invested)
                elif (actor_invested > 0 and
                      abs(actor_invested + displayed_amount - prior_highest) <= tolerance):
                    event["action"] = "call"
                    event["amount"] = prior_highest
                    event["increase"] = max(0.0, prior_highest - actor_invested)
                    event["evidence"] = f"{event.get('evidence', '')}+displayed_increment_to_call_price"
                else:
                    return False
        if event.get("action") in ("call", "bet", "raise", "reraise") and event.get("amount") in (None, 0):
            return False
        actor_previous = next((item for item in reversed(self.action_log)
                               if item.get("handId") == event.get("handId") and
                               item.get("street") == event.get("street") and
                               item.get("seat") == event.get("seat") and
                               item.get("action") not in ("blind", "post_blind", "straddle")), None)
        if (actor_previous and not actor_previous.get("inferred") and
                event.get("action") not in ("blind", "post_blind", "straddle")):
            reopened = self._action_reopened_after(self.action_log, actor_previous)
            same_capsule = (event.get("capsuleEpoch") is not None and
                            event.get("capsuleEpoch") == actor_previous.get("capsuleEpoch") and
                            event.get("action") == actor_previous.get("action"))
            prior_second = self._event_second(actor_previous)
            current_second = self._event_second(event)
            amount_correction = (
                prior_second is not None and current_second is not None and
                0 <= current_second - prior_second <= .3 and
                actor_previous.get("action") in ("bet", "raise", "reraise") and
                event.get("action") in ("bet", "raise", "reraise") and
                "." not in str(actor_previous.get("investmentText") or "") and
                "." in str(event.get("investmentText") or ""))
            if not reopened and not same_capsule and not amount_correction:
                return False
        if actor_previous and event.get("action") in ("bet", "raise", "reraise", "allin"):
            reopened = self._action_reopened_after(self.action_log, actor_previous)
            previous_second = self._event_second(actor_previous)
            event_second = self._event_second(event)
            immediate_correction = (previous_second is not None and event_second is not None and
                                    0 <= event_second - previous_second <= .3)
            if (actor_previous.get("action") in ("bet", "raise", "reraise", "allin") and
                    not reopened and not immediate_correction and
                    not actor_previous.get("pendingExactAmount")):
                return False
        if event.get("observedAt") is None:
            captured_at = getattr(self, "latest_frame_captured_at", None)
            event["observedAt"] = captured_at if captured_at is not None else time.time()
        if event.get("recognizedAt") is None:
            event["recognizedAt"] = time.time()
        event.setdefault("firstRecognizedAt", event["recognizedAt"])
        event.setdefault("confirmedAt", time.time())
        event.setdefault("frameSequence", getattr(self, "latest_frame_sequence", 0))
        if event.get("recognitionLatencyMs") is None:
            received_at = getattr(self, "frame_received_at", {}).get(event.get("frameSequence"))
            observed_at = received_at or event.get("observedAt")
            latency = max(0, event["recognizedAt"] - observed_at) * 1000 if observed_at and observed_at > 1_000_000_000 else None
            event["recognitionLatencyMs"] = None if latency is None else round(latency, 1)
        if event.get("confirmationLatencyMs") is None:
            event["confirmationLatencyMs"] = round(
                max(0, event["confirmedAt"] - event["firstRecognizedAt"]) * 1000, 1
            )
        if event.get("videoSecond") is None and hasattr(self, "recording_second"):
            event["videoSecond"] = self.recording_second
        self._replace_same_frame_inferred_action(event)
        timeline = getattr(self, "action_timeline", None)
        if timeline is not None:
            context = timeline.capture_context(
                event.get("handId"), event.get("street"), event.get("observedAt"),
                event.get("frameSequence"), event.get("videoSecond"))
            event.setdefault("capturedActionRound", context.get("actionRound"))
            event.setdefault("capturedTimeWindowId", context.get("windowId"))
        if event.get("action") in ("bet", "raise", "reraise") and float(event.get("amount") or 0) > 0:
            unresolved_allin = next((item for item in reversed(self.action_log)
                                     if item.get("handId") == event.get("handId") and
                                     item.get("street") == event.get("street") and
                                     item.get("seat") == event.get("seat") and
                                     item.get("action") == "allin" and
                                     item.get("amount") in (None, 0)), None)
            if unresolved_allin is not None:
                unresolved_allin.update(amount=event["amount"], increase=event.get("increase"),
                                        investmentText=event.get("investmentText", ""),
                                        evidence="allin_text+confirmed_investment_amount",
                                        confidence=max(float(unresolved_allin.get("confidence") or 0),
                                                       float(event.get("confidence") or 0)))
                return False
        if event.get("action") not in ("fold", "blind", "post_blind", "straddle"):
            contradicted = [item for item in self.action_log
                            if item.get("handId") == event.get("handId") and
                            item.get("street") in ("preflop", "flop", "turn", "river") and
                            item.get("seat") == event.get("seat") and
                            item.get("action") == "fold" and item.get("inferred")]
            if contradicted:
                self.action_log[:] = [item for item in self.action_log if item not in contradicted]
                self.folded_seats.discard(event.get("seat"))
                tracker = self.seat_trackers.get((event.get("seat") or 1) - 1)
                if tracker is not None and tracker.get("lastAction") == "fold":
                    tracker["lastAction"] = "waiting"
                for candidate in self.action_candidates:
                    if (candidate.get("handId") == event.get("handId") and
                            candidate.get("street") == event.get("street") and
                            candidate.get("seat") == event.get("seat") and
                            candidate.get("action") == "fold" and candidate.get("promoted")):
                            candidate.update(promoted=False, invalidated=True,
                                         invalidatedBy="later_confirmed_action")
        if event.get("action") in ("raise", "reraise"):
            prior_raises = sum(item.get("handId") == event.get("handId") and
                               item.get("street") == event.get("street") and
                               item.get("action") in ("raise", "reraise") for item in self.action_log)
            event["raiseLevel"] = prior_raises + 1
            event["actionMeaning"] = "raise" if prior_raises == 0 else "re_raise"
        if resolve_prior and event.get("action") not in ("blind", "post_blind", "straddle"):
            self._promote_expected_fold_chain()
        if resolve_prior and event.get("action") not in ("blind", "post_blind", "straddle", "fold"):
            self._promote_prior_fold_candidates((event.get("seat") or 1) - 1)
        capsule_epoch = event.get("capsuleEpoch")
        if capsule_epoch is not None:
            existing_capsule = next((item for item in self.action_log
                                     if item.get("handId") == event.get("handId") and
                                     item.get("street") == event.get("street") and
                                     item.get("seat") == event.get("seat") and
                                     item.get("action") == event.get("action") and
                                     item.get("capsuleEpoch") == capsule_epoch), None)
            if existing_capsule is not None:
                existing_second = self._event_second(existing_capsule)
                event_second = self._event_second(event)
                timely_recheck = (existing_second is not None and event_second is not None and
                                  0 <= float(event_second) - float(existing_second) <= 1.5)
                intervening_action = any(
                    item.get("handId") == event.get("handId") and
                    item.get("street") == event.get("street") and
                    item.get("seat") != event.get("seat") and
                    float(self._event_second(item) or 0) > float(existing_second or 0)
                    for item in self.action_log[self.action_log.index(existing_capsule) + 1:]
                )
                reopened_capsule = (
                    event.get("action") == "call" and
                    self._action_reopened_after(self.action_log, existing_capsule)
                )
                if not timely_recheck or intervening_action:
                    timely_recheck = False
            if existing_capsule is not None and not reopened_capsule:
                old_text = str(existing_capsule.get("investmentText") or "")
                new_text = str(event.get("investmentText") or "")
                old_decimals = len(old_text.rsplit(".", 1)[1]) if "." in old_text else 0
                new_decimals = len(new_text.rsplit(".", 1)[1]) if "." in new_text else 0
                clearer_amount = (timely_recheck and not intervening_action and
                                  event.get("amount") is not None and
                                  ((not old_decimals and new_decimals) or
                                   (old_decimals >= 3 and 1 <= new_decimals <= 2)) and
                                  event.get("amount") != existing_capsule.get("amount"))
                if ((existing_capsule.get("amount") is None and event.get("amount") is not None) or
                        clearer_amount):
                    existing_capsule["amount"] = event.get("amount")
                    existing_capsule["increase"] = event.get("increase")
                    existing_capsule["evidence"] = event.get("evidence")
                    existing_capsule["confidence"] = max(float(existing_capsule.get("confidence") or 0),
                                                         float(event.get("confidence") or 0))
                    existing_capsule["investmentText"] = event.get("investmentText", "")
                    tracker = self.seat_trackers.get((event.get("seat") or 1) - 1)
                    if tracker is not None:
                        tracker["stableBet"] = event.get("amount")
                return False
        same_actor_action = next((item for item in reversed(self.action_log)
                                  if item.get("handId") == event.get("handId") and
                                  item.get("street") == event.get("street") and
                                  item.get("seat") == event.get("seat") and
                                  item.get("action") == event.get("action")), None)
        latest_actor_event = next((item for item in reversed(self.action_log)
                                   if item.get("handId") == event.get("handId") and
                                   item.get("street") == event.get("street") and
                                   item.get("seat") == event.get("seat")), None)
        if latest_actor_event and event.get("action") in ("bet", "raise", "reraise") and \
                latest_actor_event.get("action") in ("bet", "raise", "reraise"):
            latest_second = self._event_second(latest_actor_event)
            event_second = self._event_second(event)
            close = (latest_second is not None and event_second is not None and
                     0 <= event_second - latest_second <= 1.0)
            no_new_amount = event.get("amount") is None or event.get("amount") == latest_actor_event.get("amount")
            if close and no_new_amount:
                return False
            investment_text = str(event.get("investmentText") or "")
            prior_amount = latest_actor_event.get("amount")
            amount = event.get("amount")
            pot_after = event.get("potAfter")
            decimal_loss = (close and event_second - latest_second <= .3 and
                            prior_amount not in (None, 0) and amount not in (None, 0) and
                            amount >= prior_amount * 5 and "." not in investment_text and
                            (pot_after is None or amount > max(1.0, pot_after * 3)))
            prior_text = str(latest_actor_event.get("investmentText") or "")
            corrected_decimal = (close and event_second - latest_second <= .3 and
                                 prior_amount not in (None, 0) and amount not in (None, 0) and
                                 "." not in prior_text and "." in investment_text and
                                 amount > prior_amount)
            if corrected_decimal:
                prior_increase = float(latest_actor_event.get("increase") or 0)
                latest_actor_event.update(
                    amount=amount,
                    increase=round(prior_increase + amount - prior_amount, 6),
                    investmentText=investment_text,
                    evidence=f"清晰小数金额复核→{amount:g}",
                    confidence=max(float(latest_actor_event.get("confidence") or 0),
                                   float(event.get("confidence") or 0)),
                )
                tracker = self.seat_trackers.get((event.get("seat") or 1) - 1)
                if tracker is not None:
                    tracker["stableBet"] = amount
                return False
            if decimal_loss:
                return False
        if same_actor_action:
            later = self.action_log[self.action_log.index(same_actor_action) + 1:]
            action = event.get("action")
            if action in ("fold", "check", "bet", "allin"):
                return False
            if action == "call" and not any(
                    item.get("handId") == event.get("handId") and
                    item.get("street") == event.get("street") and
                    item.get("seat") != event.get("seat") and
                    item.get("action") in ("bet", "raise", "reraise", "allin")
                    for item in later):
                return False
            if action in ("raise", "reraise") and not any(
                    item.get("handId") == event.get("handId") and
                    item.get("street") == event.get("street") and
                    item.get("seat") != event.get("seat") and
                    item.get("action") in ("raise", "reraise", "allin")
                    for item in later):
                return False
        if event.get("action") == "post_blind":
            self.action_log[:] = [item for item in self.action_log if not (
                item.get("handId") == event.get("handId") and item.get("street") == "preflop" and
                item.get("seat") == event.get("seat") and item.get("amount") == event.get("amount") and
                item.get("action") == "bet")]
        if ActionLedgerLayer.is_recent_duplicate(self.action_log, event):
            return False
        if pending_aggressive_correction is not None:
            correction_target = pending_aggressive_correction.pop("event")
            correction_target.update(pending_aggressive_correction)
        ActionLedgerLayer.normalize_street_time(self.action_log, event)
        event.setdefault("chainStatus", "direct_confirmed" if not event.get("inferred") else "rule_confirmed")
        hero_index = 4 if self.layout == "8max" else 3
        if (event.get("seat") == hero_index + 1 and
                event.get("action") not in ("blind", "post_blind", "straddle")):
            release_context = getattr(self, "hero_button_release_context", None)
            if (release_context and
                    release_context.get("handId") == event.get("handId") and
                    release_context.get("street") == event.get("street")):
                event.setdefault("actionButtonSequence",
                                 release_context.get("actionButtonSequence"))
        preselection = None
        candidate = self.action_button_preselection
        if (candidate and candidate.get("handId") == event.get("handId") and
                candidate.get("street") == event.get("street")):
            preselection = candidate
        if not preselection:
            preselection = self._matching_hero_preselection()
        allowed_preselected_actions = ({"fold", "check"} if preselection and
                                       preselection.get("side") == "left" else
                                       {"check", "call"})
        if (event.get("seat") == hero_index + 1 and preselection and
                event.get("action") in allowed_preselected_actions):
            event["preselected"] = True
            event["preselection"] = dict(preselection)
            event.setdefault("actionButtonSequence", preselection.get("actionButtonSequence"))
            self.hero_preselection = None
        if (event.get("seat") == hero_index + 1 and
                event.get("action") not in ("blind", "post_blind", "straddle")):
            self.hero_preselection = None
            self.action_button_preselection = None
        event["strategyEligible"] = not event.get("visualCandidate") and not event.get("orderConflict")
        if event.get("potBefore") is None:
            increase = event.get("increase")
            pot_after = event.get("potAfter")
            previous_pot = next((item.get("potAfter") for item in reversed(self.action_log)
                                 if item.get("handId") == event.get("handId") and
                                 isinstance(item.get("potAfter"), (int, float))), None)
            if isinstance(pot_after, (int, float)) and isinstance(increase, (int, float)):
                event["potBefore"] = round(max(0.0, float(pot_after) - float(increase)), 6)
            elif isinstance(previous_pot, (int, float)):
                event["potBefore"] = round(float(previous_pot), 6)
        if event.get("betPotRatio") is None:
            increase = event.get("increase")
            pot_before = event.get("potBefore")
            if (event.get("action") in ("bet", "raise", "reraise", "allin") and
                    isinstance(increase, (int, float)) and
                    isinstance(pot_before, (int, float)) and pot_before > 0):
                event["betPotRatio"] = round(float(increase) / float(pot_before), 4)
        seat_index = ActionLedgerLayer.record_participant(
            self.hand_participants, self.seat_trackers, event)
        self.action_log.append(event)
        formal_commit = self._commit_formal_action_ledger(event)
        if formal_commit["status"] == "rejected":
            self.action_log[:] = [item for item in self.action_log if not (
                item.get("handId") == event.get("handId") and
                item.get("street") == event.get("street") and
                item.get("seat") == event.get("seat") and
                item.get("action") == event.get("action") and
                self._event_second(item) == self._event_second(event)
            )]
            return False
        if (seat_index == hero_index and
                event.get("action") not in ("blind", "post_blind", "straddle")):
            hero_candidate = next((item for item in reversed(self.action_candidates)
                                   if item.get("handId") == event.get("handId") and
                                   item.get("street") == event.get("street") and
                                   item.get("seat") == event.get("seat") and
                                   item.get("action") == "hero_action_unresolved" and
                                   not item.get("promoted") and not item.get("expired")), None)
            if hero_candidate is not None:
                hero_candidate["promoted"] = True
            self.pending_hero_buttons = []
            self.pending_hero_hand_id = None
            self.pending_hero_street = None
        prior_unresolved = getattr(self, "prior_street_unresolved", None)
        if (prior_unresolved and event.get("street") == self.hand_state.get("street") and
                event.get("seat")):
            prior_unresolved.get("seats", set()).discard(event["seat"] - 1)
        if event.get("action") not in ("blind", "post_blind", "straddle"):
            self.waiting_for_forced_bets = False
        if event.get("action") == "fold" and event.get("seat"):
            self.folded_seats.add(event["seat"])
        if event.get("action") == "straddle" and event.get("street") == "preflop" and event.get("seat"):
            self._advance_after_confirmed_straddle(event["seat"] - 1, event.get("handId"))
            event["nextExpectedSeat"] = (self.formal_expected_seat + 1
                                         if self.formal_expected_seat is not None else None)
        elif event.get("action") not in ("blind", "post_blind", "straddle") and event.get("seat"):
            self.formal_expected_seat = self._next_opponent_seat(event["seat"] - 1)
            event["nextExpectedSeat"] = (self.formal_expected_seat + 1
                                         if self.formal_expected_seat is not None else None)
        if hasattr(self, "pipeline_timestamps"):
            self._mark_pipeline("action_confirmed", handId=event.get("handId"), seat=event.get("seat"),
                                action=event.get("action"), frameSequence=event.get("frameSequence"),
                                latencyMs=event.get("recognitionLatencyMs"))
        self._rebuild_action_timeline(event.get("handId"), event.get("street"), event)
        chain = formal_commit["snapshot"]
        if self._repair_rule_proven_folds_before_action(event, chain):
            chain = self._action_chain_snapshot(event.get("handId"), event.get("street"))
        if (event.get("handId") == self.hand_state.get("id") and
                event.get("street") == self.hand_state.get("street")):
            missing = next((item.get("missingSeats") or []
                            for item in chain.get("conflicts") or []
                            if item.get("missingSeats")), [])
            if missing:
                self.formal_expected_seat = int(missing[0]) - 1
            elif chain.get("nextActor") is not None:
                self.formal_expected_seat = chain["nextActor"]
        self._compare_shadow_action_engine(event, chain)
        ordered_event = next((item for item in self.action_log
                              if item.get("handId") == event.get("handId") and
                              item.get("street") == event.get("street") and
                              item.get("seat") == event.get("seat") and
                              item.get("action") == event.get("action") and
                              self._event_second(item) == self._event_second(event)), None)
        if (ordered_event and not ordered_event.get("orderConflict") and
                ordered_event.get("strategyEligible", True) and
                float(ordered_event.get("confidence") or 0) >= ACTION_STRATEGY_CONFIDENCE):
            event_second = self._event_second(ordered_event)
            for prior in self.action_log:
                confidence = float(prior.get("confidence") or 0)
                prior_highest = prior.get("priorHighestBet")
                prior_amount = prior.get("amount")
                unmatched_price = (
                    isinstance(prior_highest, (int, float)) and
                    isinstance(prior_amount, (int, float)) and
                    float(prior_highest) > float(prior_amount) +
                    max(.001, float(prior_highest) * .02)
                )
                if (prior is ordered_event or prior.get("handId") != event.get("handId") or
                        prior.get("street") != event.get("street") or
                        prior.get("action") != "fold" or
                        prior.get("evidence") != "头像弃牌文字" or
                        prior.get("orderConflict") or
                        not prior.get("strategyEligible", True) or
                        confidence >= ACTION_STRATEGY_CONFIDENCE or
                        not (confidence >= .72 or (confidence > 0 and unmatched_price))):
                    continue
                prior_second = self._event_second(prior)
                if (event_second is not None and prior_second is not None and
                        float(event_second) < float(prior_second)):
                    continue
                prior["sourceConfidence"] = prior.get("confidence")
                prior["confidence"] = .88
                prior["evidence"] = ("头像弃牌文字+后续合法动作顺序确认" if confidence >= .72 else
                                     "头像弃牌文字+后续合法动作顺序+未补齐投入确认")
                prior["chainStatus"] = "cross_checked"
        self.pending_history_events.append(event)
        self._record_hero_strategy_comparison(event)
        self._publish_confirmed_action_state(event)
        self._publish_action_audit(event)
        return True

    def _confirm_prior_street_check(self, event):
        prior = getattr(self, "prior_street_unresolved", None)
        seat = event.get("seat")
        if (not prior or not seat or event.get("handId") != self.hand_state.get("id") or
                event.get("street") == prior.get("street") or prior.get("repairing")):
            return False
        proof = ActionEngine.prove_prior_street_action(self.action_log, event, prior)
        if proof is None:
            return False
        action = proof["action"]
        prior["repairing"] = True
        repaired = {
            "time": time.time(), "observedAt": prior.get("changedAt"),
            "videoSecond": prior.get("changedAt"), "handId": event.get("handId"),
            "street": prior.get("street"), "seat": seat,
            "name": self.seat_trackers.get(seat - 1, {}).get("name", ""),
            "action": action, "amount": proof["amount"], "increase": proof["increase"],
            "confidence": .95, "inferred": True, "chainStatus": "rule_confirmed",
            "strategyEligible": True,
            "evidence": ("next_street_same_player_action+only_unacted+no_call_deficit"
                         if action == "check" else
                         "next_street_same_player_action+only_unacted+call_deficit_closed"),
        }
        try:
            confirmed = self._append_action_event(repaired, resolve_prior=False)
        finally:
            prior["repairing"] = False
        if confirmed:
            prior.get("seats", set()).discard(seat - 1)
        return confirmed

    def _event_sort_key(self, item):
        street = item.get("street")
        if street != "preflop" or item.get("action") in ("blind", "post_blind"):
            return (item.get("handId", 0), street or "", 1,
                    item.get("videoSecond") if item.get("videoSecond") is not None else float("inf"),
                    item.get("time", 0))
        seat = (item.get("seat") or 1) - 1
        order_map = self._street_action_order(street)
        order = order_map.get(seat, len(order_map) + seat)
        return (item.get("handId", 0), street, 0, order,
                item.get("videoSecond") if item.get("videoSecond") is not None else float("inf"))

    def _street_action_order(self, street):
        """Return the current hand's clockwise order, skipping empty/folded seats."""
        count = len(TABLE_LAYOUTS[self.layout])
        dealer = self.hand_dealer_index
        if dealer is None:
            return {index: index for index in range(count)}
        occupied = [index for index, tracker in self.seat_trackers.items()
                    if tracker.get("occupancy") == "occupied" and tracker.get("handEligible", True)]
        folded = {item.get("seat", 0) - 1 for item in self.action_log
                  if item.get("handId") == self.hand_state.get("id") and
                  item.get("street") == street and item.get("action") == "fold"}
        occupied = [index for index in occupied if index not in folded]
        if street == "preflop":
            small = self._next_occupied_seat_from_indices(occupied, dealer, count)
            big = self._next_occupied_seat_from_indices(occupied, small, count)
            start = self._next_occupied_seat_from_indices(occupied, big, count)
        else:
            start = self._next_occupied_seat_from_indices(occupied, dealer, count)
        if start is None:
            return {}
        order = {}
        for offset in range(count):
            seat = (start + offset) % count
            if seat in occupied:
                order[seat] = len(order)
        return order

    @staticmethod
    def _next_occupied_seat_from_indices(occupied, current, count):
        if not occupied or current is None:
            return None
        for offset in range(1, count + 1):
            candidate = (current + offset) % count
            if candidate in occupied:
                return candidate
        return None

    def _capture_fast_actions_for_frame(self, frame, pot_after, capture_context):
        try:
            return self._capture_fast_actions(
                frame, pot_after, capture_context=capture_context)
        except TypeError as error:
            if "capture_context" not in str(error):
                raise
            return self._capture_fast_actions(frame, pot_after)

    def _capture_fast_actions_for_seat_context(self, frame, pot_after, focus_seat,
                                               capture_context):
        try:
            return self._capture_fast_actions_for_seat(
                frame, pot_after, focus_seat, capture_context)
        except TypeError as error:
            if ("positional argument" not in str(error) and
                    "capture_context" not in str(error)):
                raise
            return self._capture_fast_actions_for_seat(frame, pot_after, focus_seat)

    def _capture_fast_actions_for_seat(self, frame, pot_after, focus_seat,
                                       capture_context=None):
        try:
            return self._capture_fast_actions(
                frame, pot_after, focus_seat=focus_seat,
                capture_context=capture_context)
        except TypeError as error:
            message = str(error)
            if "capture_context" in message:
                try:
                    return self._capture_fast_actions(
                        frame, pot_after, focus_seat=focus_seat)
                except TypeError as retry_error:
                    if "focus_seat" not in str(retry_error):
                        raise
            elif "focus_seat" not in message:
                raise
            return self._capture_fast_actions(frame, pot_after)

    def _capture_fast_actions(self, frame, pot_after=None, focus_seat=None,
                              capture_context=None):
        events = self._drain_action_ocr_results()
        observations = []
        capture_context = dict(
            capture_context or self._new_capture_context(
                self.latest_frame_captured_at, self.latest_frame_sequence,
                self.latest_frame_video_second))
        captured_runtime = capture_context.get("runtimeId", self.runtime_id)
        captured_session = capture_context.get("tableSession", self.table_session)
        captured_hand = capture_context.get("handId", self.hand_state.get("id", 0))
        captured_street = capture_context.get("street", self.hand_state.get("street", "waiting"))
        captured_at = capture_context.get("observedAt")
        captured_sequence = capture_context.get("frameSequence")
        captured_video_second = capture_context.get("videoSecond")
        if (captured_runtime != self.runtime_id or captured_session != self.table_session or
                captured_hand != self.hand_state.get("id")):
            return events
        height, width = frame.shape[:2]
        hero_index = 4 if self.layout == "8max" else 3
        expected_action_seat = getattr(self, "formal_expected_seat", None)
        prior_street_probe_seats = set(self._prior_street_probe_seats())
        chain_gap_contexts = self._current_street_chain_gap_contexts()
        chain_gap_probe_seats = set(chain_gap_contexts)
        if focus_seat in range(len(TABLE_LAYOUTS[self.layout])):
            seat_indices = [focus_seat]
        else:
            seat_indices = list(range(len(TABLE_LAYOUTS[self.layout])))
        if expected_action_seat in seat_indices:
            seat_indices = seat_indices[expected_action_seat:] + seat_indices[:expected_action_seat]
        for index in seat_indices:
            targeted_hero_probe = focus_seat == index
            prior_street_probe = index in prior_street_probe_seats
            chain_gap_probe = index in chain_gap_probe_seats
            relative_x, relative_y = TABLE_LAYOUTS[self.layout][index]
            if (index == hero_index and index != expected_action_seat and
                    not self.pending_hero_buttons and
                    not getattr(self, "waiting_for_forced_bets", False)):
                continue
            tracker = self.seat_trackers.get(index)
            if not tracker or tracker.get("occupancy") != "occupied":
                continue
            cx, cy = int(width * relative_x), int(height * relative_y)
            radius = int(width * .065)
            dictionary_box = self._seat_slot_box(index, "action", width, height)
            if dictionary_box:
                box = dictionary_box
            elif relative_y < .22:
                box = (cx - int(radius * 1.25), cy + int(radius * 2.45),
                       cx + int(radius * 1.25), cy + int(radius * 3.75))
            elif relative_x < .42:
                box = (cx + int(radius * .55), cy - int(radius * 1.05),
                       cx + int(radius * 3.1), cy + int(radius * 1.65))
            elif relative_x > .58:
                box = (cx - int(radius * 3.1), cy - int(radius * 1.05),
                       cx - int(radius * .55), cy + int(radius * 1.65))
            else:
                box = (cx - int(radius * 2.1), cy + int(radius * .65),
                       cx + int(radius * 2.1), cy + int(radius * 2.3))
            x1, y1, x2, y2 = (max(0, box[0]), max(0, box[1]), min(width, box[2]), min(height, box[3]))
            if relative_y < .22:
                y2 = min(y2, int(height * .24))
            center_x1, center_y1, center_x2, center_y2 = width * .28, height * .242, width * .72, height * .338
            if relative_y >= .22 and x1 < center_x2 and x2 > center_x1 and y1 < center_y2 and y2 > center_y1:
                if relative_x < .5:
                    x2 = min(x2, int(center_x1))
                else:
                    x1 = max(x1, int(center_x2))
            crop = frame[y1:y2, x1:x2]
            avatar_box = self._seat_slot_box(index, "avatar", width, height)
            ax1, ay1, ax2, ay2 = avatar_box
            avatar = frame[max(0, ay1):min(height, ay2), max(0, ax1):min(width, ax2)]
            state_avatar = avatar
            investment_box = self._seat_slot_box(index, "investment", width, height)
            ix1, iy1, ix2, iy2 = investment_box
            investment = frame[max(0, iy1):min(height, iy2), max(0, ix1):min(width, ix2)]
            stack_box = self._seat_slot_box(index, "chips", width, height)
            sx1, sy1, sx2, sy2 = stack_box
            stack = frame[max(0, sy1):min(height, sy2), max(0, sx1):min(width, sx2)]
            if crop.size == 0:
                continue
            self.action_crop_history[index].append({
                "image": crop.copy(),
                "avatar": state_avatar.copy(),
                "investment": investment.copy(),
                "stack": stack.copy(),
                "runtimeId": captured_runtime,
                "tableSession": captured_session,
                "handId": captured_hand,
                "street": captured_street,
                "observedAt": captured_at if captured_at is not None else time.time(),
                "frameSequence": captured_sequence,
                "videoSecond": captured_video_second,
            })
            action_signature = cv2.resize(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), (32, 16), interpolation=cv2.INTER_AREA)
            avatar_signature = cv2.resize(cv2.cvtColor(avatar, cv2.COLOR_BGR2GRAY), (16, 16), interpolation=cv2.INTER_AREA)
            confirmed_fold_signature = tracker.get("confirmedFoldSignature")
            fold_signature_match = bool(
                confirmed_fold_signature is not None and
                float(np.mean(cv2.absdiff(avatar_signature, confirmed_fold_signature))) <= 12.0
            )
            if confirmed_fold_signature is not None and not fold_signature_match:
                tracker.pop("confirmedFoldSignature", None)
            investment_signature = cv2.resize(cv2.cvtColor(investment, cv2.COLOR_BGR2GRAY),
                                              (16, 16), interpolation=cv2.INTER_AREA)
            signature = np.hstack((action_signature, avatar_signature, investment_signature))
            previous = self.fast_action_signatures.get(index)
            signature_delta = float(np.mean(cv2.absdiff(signature, previous))) if previous is not None else 255.0
            action_delta = (float(np.mean(cv2.absdiff(action_signature, previous[:, :32])))
                            if previous is not None else 255.0)
            avatar_delta = (float(np.mean(cv2.absdiff(avatar_signature, previous[:, 32:48])))
                            if previous is not None else 255.0)
            investment_delta = (float(np.mean(cv2.absdiff(investment_signature, previous[:, 48:64])))
                                if previous is not None else 255.0)
            self.fast_action_signatures[index] = signature
            model_fold = (
                self._avatar_is_fold_for_frame(index, avatar, captured_sequence)
                if (avatar_delta >= 6.0 or index == expected_action_seat or
                    targeted_hero_probe or prior_street_probe) else False
            )
            fold_candidate = model_fold
            avatar_contrast = float(np.std(cv2.cvtColor(avatar, cv2.COLOR_BGR2GRAY)))
            history = self.avatar_contrast_history[index]
            contrast_fold = bool(history and max(history) - avatar_contrast >= 25 and avatar_contrast < 40)
            history.append(avatar_contrast)
            fold_candidate = fold_candidate or contrast_fold
            terminal_action_logged = any(
                item.get("handId") == captured_hand and
                item.get("street") == captured_street and
                item.get("seat") == index + 1 and
                item.get("action") in ("fold", "allin")
                for item in self.action_log
            )
            self.avatar_fold_frames[index] = self.avatar_fold_frames.get(index, 0) + 1 if fold_candidate else 0
            if fold_candidate or fold_signature_match:
                self.avatar_state_clear_frames[index] = 0
                current_second = captured_video_second
                for candidate in reversed(self.action_candidates):
                    if (candidate.get("handId") == captured_hand and
                            candidate.get("street") == captured_street and
                            candidate.get("seat") == index + 1 and
                            candidate.get("action") == "fold" and
                            not candidate.get("promoted") and not candidate.get("expired")):
                        candidate["lastSeenSecond"] = current_second
                        break
            else:
                self.avatar_state_clear_frames[index] = self.avatar_state_clear_frames.get(index, 0) + 1
                if self.avatar_state_clear_frames[index] >= 5:
                    self.avatar_state_latched[index] = False
            if self.avatar_fold_frames[index] >= 2 and not terminal_action_logged:
                observed_at = captured_at if captured_at is not None else time.time()
                event = {"time": time.time(), "observedAt": observed_at,
                         "frameSequence": captured_sequence, "handId": captured_hand,
                         "street": captured_street, "runtimeId": captured_runtime,
                         "tableSession": captured_session, "sequence": 1, "seat": index + 1,
                         "name": tracker.get("name", ""), "action": "fold", "amount": tracker.get("stableBet", 0),
                         "increase": 0, "chipsAfter": tracker.get("chips"), "potAfter": pot_after,
                         "confidence": .72, "evidence": "头像弃牌模型连续2帧", "visualCandidate": True}
                event["evidenceSignals"] = {"avatarModel": bool(model_fold),
                                            "contrastDrop": bool(contrast_fold)}
                if self._append_action_candidate(event):
                    events.append(event)
            if avatar_delta >= 6.0:
                self.avatar_state_latched[index] = False
            avatar_state_window = (
                (avatar_delta >= 8.0 or self.avatar_fold_frames.get(index, 0) == 2) and
                not self.avatar_state_latched.get(index)
            )
            if (index == expected_action_seat and model_fold and
                    self.avatar_fold_frames.get(index, 0) == 2):
                avatar_state_window = True
            observed_at = captured_at if captured_at is not None else time.time()
            expected_scan_due = ((index == expected_action_seat or targeted_hero_probe or
                                  prior_street_probe) and
                                 not terminal_action_logged and
                                 observed_at - self.expected_avatar_scan_at.get(index, float("-inf")) >= .12)
            if expected_scan_due:
                avatar_state_window = True
            changed = (previous is None or signature_delta >= 5.0 or investment_delta >= 1.5 or
                    avatar_state_window or index == expected_action_seat)
            small_blind_probe, big_blind_probe, straddle_probe = self._current_forced_bet_seats()
            forced_straddle_probe = (getattr(self, "waiting_for_forced_bets", False) and
                                     index == straddle_probe and
                                     not any(item.get("handId") == captured_hand and
                                             item.get("seat") == index + 1 and
                                             item.get("action") == "straddle"
                                             for item in self.action_log) and
                                     (captured_video_second or 0) -
                                     getattr(self, "last_forced_straddle_probe", float("-inf")) >= .08)
            if forced_straddle_probe:
                self.last_forced_straddle_probe = captured_video_second or 0
            changed = changed or forced_straddle_probe
            retry_unresolved = self.action_unresolved_retries.get(index, 0) > 0
            if retry_unresolved:
                self.action_unresolved_retries[index] -= 1
            if not changed and not retry_unresolved and not (tracker.get("pendingBet") is not None and tracker.get("betFrames", 0) < 2):
                continue
            expected_action_probe = ((index == expected_action_seat or targeted_hero_probe) and
                                     not terminal_action_logged and
                                     not getattr(self, "waiting_for_forced_bets", False))
            color_action, color_confidence = self._classify_action_color(crop)
            pending_bet = tracker.get("pendingBet") is not None and tracker.get("betFrames", 0) < 2
            action_window = bool(color_action or retry_unresolved or pending_bet or expected_action_probe)
            small_blind, big_blind, straddle_seat = self._current_forced_bet_seats()
            recorded_forced_actions = {
                (item.get("seat"), item.get("action"))
                for item in self.action_log
                if item.get("handId") == captured_hand and item.get("street") == "preflop"
            }
            forced_blind_window = (getattr(self, "waiting_for_forced_bets", False) and
                                   index in (small_blind, big_blind) and
                                   (index + 1, "blind") not in recorded_forced_actions)
            forced_straddle_window = (getattr(self, "waiting_for_forced_bets", False) and
                                      index == straddle_seat and
                                      (index + 1, "straddle") not in recorded_forced_actions and
                                      (bool(color_action) or action_delta >= 5.0 or investment_delta >= 1.5))
            # The opening straddle may not use the same colour capsule as a
            # normal action.  The dedicated probe is therefore itself enough
            # to enqueue the specialised OCR job; it must not be discarded by
            # the generic action-window gate below.
            forced_straddle_window = forced_straddle_window or forced_straddle_probe
            straddle_label = bool(forced_straddle_window and self._is_straddle_label(crop))
            straddle_amount = None
            if (getattr(self, "allow_inline_fast_ocr", False) and
                    getattr(self, "waiting_for_forced_bets", False) and index == straddle_seat and
                    (index + 1, "straddle") not in recorded_forced_actions and investment.size):
                amount_text, amount_confidence = self._ocr_line(cv2.resize(
                    investment, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC))
                parsed_amount = self._extract_investment_amount(amount_text)
                known_big = float(self.blind_amounts.get("big") or 0)
                if (parsed_amount not in (None, 0) and known_big > 0 and
                        abs(float(parsed_amount) - known_big * 2) <= max(.01, known_big * .12) and
                        amount_confidence >= .35):
                    straddle_amount = round(known_big * 2, 4)
                    forced_straddle_window = True
                    straddle_label = True
            if forced_blind_window or forced_straddle_window:
                action_window = True
            if expected_scan_due:
                avatar_state_window = True
            if not action_window and not avatar_state_window:
                self.action_capsule_visible[index] = False
                self.active_color_actions[index] = None
                continue
            crop_history = [item for item in self.action_crop_history[index]
                            if item.get("handId") == captured_hand]
            job = {"index": index, "name": tracker.get("name", ""), "chips": tracker.get("chips"),
                   "crops": [{**item, "image": item["image"].copy(),
                              "avatar": item["avatar"].copy(),
                              "investment": item["investment"].copy(),
                              "stack": item["stack"].copy()} for item in crop_history],
                   "avatar": state_avatar.copy(),
                   "avatarSignature": avatar_signature.copy(),
                   "investment": investment.copy(), "stack": frame[max(0, self._seat_slot_box(index, "chips", width, height)[1]):min(height, self._seat_slot_box(index, "chips", width, height)[3]),
                                                   max(0, self._seat_slot_box(index, "chips", width, height)[0]):min(width, self._seat_slot_box(index, "chips", width, height)[2])].copy() if self._seat_slot_box(index, "chips", width, height) else None,
                   "potAfter": pot_after,
                   "avatarStateCandidate": bool(avatar_state_window),
                   "runtimeId": captured_runtime, "tableSession": captured_session,
                   "handId": captured_hand, "street": captured_street,
                   "observedAt": captured_at if captured_at is not None else time.time(),
                   "frameReceivedAt": self.frame_received_at.get(captured_sequence),
                   "frameSequence": captured_sequence,
                   "videoSecond": captured_video_second}
            captured_events = [
                item for item in self.action_log
                if item.get("handId") == job["handId"] and item.get("street") == job["street"]
            ]
            captured_investments = [
                float(item.get("amount") or 0) for item in captured_events
                if item.get("action") in ("blind", "post_blind", "straddle", "call",
                                          "bet", "raise", "reraise", "allin")
            ]
            job.update(
                highestBetAtCapture=max(captured_investments, default=0.0),
                actorBetAtCapture=float(tracker.get("stableBet") or 0),
                confirmedActionCountAtCapture=len(captured_events),
                expectedSeatAtCapture=expected_action_seat,
            )
            job["visualFoldCandidate"] = bool(fold_candidate)
            job["avatarChanged"] = bool(avatar_delta >= 8.0)
            job["expectedActor"] = bool(index == expected_action_seat)
            job["expectedActionProbe"] = expected_action_probe
            job["priorStreetProbe"] = prior_street_probe
            job["chainGapProbe"] = chain_gap_probe
            if chain_gap_probe:
                job["chainGapContext"] = dict(chain_gap_contexts[index])
            if forced_blind_window:
                job["forcedAction"] = "blind"
                job["forcedSeatValidation"] = (
                    index == hero_index or
                    tracker.get("visualState") in ("waiting", "away", "empty")
                )
                role = "small" if index == small_blind else "big"
                known_amount = self.blind_amounts.get(role)
                if known_amount not in (None, 0):
                    job["forcedAmount"] = float(known_amount)
            if forced_straddle_window:
                job["forcedStraddleWindow"] = True
                if straddle_label:
                    job["forcedAction"] = "straddle"
                    job["forcedAmount"] = straddle_amount or float(self.blind_amounts.get("big") or 0) * 2
            trigger_source = ("forced_bet_scan" if (forced_blind_window or forced_straddle_window) else
                              "prior_street_probe" if prior_street_probe else
                              "capsule_color" if color_action else
                              "unresolved_retry" if retry_unresolved else
                              "pending_bet" if pending_bet else
                              "avatar_delta")
            job["triggerSource"] = trigger_source
            self.action_trigger_counts[trigger_source] = self.action_trigger_counts.get(trigger_source, 0) + 1
            if avatar_state_window:
                self.avatar_state_latched[index] = True
                if index == expected_action_seat:
                    self.expected_avatar_scan_at[index] = observed_at
            if color_action:
                if not self.action_capsule_visible[index]:
                    self.action_capsule_epochs[index] += 1
                self.action_capsule_visible[index] = True
                self.active_color_actions[index] = color_action
                self.action_capsule_last_seen[index] = captured_video_second
                job["capsuleDetected"] = True
                job["colorAction"] = color_action
                job["capsuleColorConfidence"] = color_confidence
                job["capsuleEpoch"] = self.action_capsule_epochs[index]
                if (getattr(self, "allow_inline_fast_ocr", False) and
                        color_action != "check" and investment.size):
                    amount_text, amount_confidence = self._ocr_line(cv2.resize(
                        investment, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC))
                    amount = self._extract_investment_amount(amount_text)
                    if amount not in (None, 0) and amount_confidence >= .5:
                        job["knownInvestmentAmount"] = amount
                        job["knownInvestmentText"] = amount_text
                    job["fastInvestmentText"] = amount_text
                    job["fastInvestmentConfidence"] = amount_confidence
                    job["fastInvestmentAmount"] = amount
                if color_action in ("call", "check"):
                    highest = max(
                        [float(value.get("stableBet") or 0) for key, value in self.seat_trackers.items()
                         if key != index] +
                        [float(item.get("amount") or 0) for item in self.action_log
                         if item.get("handId") == job["handId"] and
                         item.get("street") == job["street"] and item.get("seat") != index + 1],
                        default=0.0,
                    )
                    actor_bet = float(tracker.get("stableBet") or 0)
                    chips = tracker.get("chips")
                    required = max(0.0, highest - actor_bet)
                    if highest > actor_bet:
                        job["knownCallAmount"] = highest
                        if color_action == "check":
                            job["forceActionTextOcr"] = True
            else:
                self.action_capsule_visible[index] = False
                self.active_color_actions[index] = None
            try:
                avatar_priority = ((avatar_state_window or chain_gap_probe) and
                                   not color_action and not pending_bet and
                                   not forced_blind_window and not forced_straddle_window and
                                   (chain_gap_probe or not action_window or
                                    index == expected_action_seat))
                if avatar_priority:
                    job["fastLineOnly"] = bool(index == expected_action_seat)
                    try:
                        with self.avatar_ocr_pending_lock:
                            if index in self.avatar_ocr_pending_seats:
                                if job.get("visualFoldCandidate"):
                                    self.avatar_ocr_deferred_jobs[index] = job
                                continue
                            self.avatar_ocr_pending_seats.add(index)
                        self._enqueue_avatar_ocr(job)
                    except queue.Full:
                        with self.avatar_ocr_pending_lock:
                            self.avatar_ocr_pending_seats.discard(index)
                    continue
                if job.get("capsuleDetected"):
                    confirmed = next((item for item in reversed(self.action_log)
                                      if item.get("handId") == job.get("handId") and
                                      item.get("street") == job.get("street") and
                                      item.get("seat") == index + 1 and
                                      item.get("capsuleEpoch") == job.get("capsuleEpoch")), None)
                    if confirmed is not None and confirmed.get("action") == "check":
                        continue
                    if confirmed is not None and confirmed.get("action") == "call":
                        highest = max((float(item.get("amount") or 0) for item in self.action_log
                                       if item.get("handId") == job.get("handId") and
                                       item.get("street") == job.get("street") and
                                       item.get("seat") != index + 1 and
                                       item.get("action") in ("bet", "raise", "reraise", "allin", "straddle")),
                                      default=0.0)
                        amount = float(confirmed.get("amount") or 0)
                        if highest > 0 and abs(amount - highest) <= max(.01, highest * .08):
                            continue
                with self.action_ocr_pending_lock:
                    if index in self.action_ocr_pending_seats:
                        self._defer_action_ocr_job(index, job)
                        continue
                    self.action_ocr_pending_seats.add(index)
                self._enqueue_action_ocr(job)
            except queue.Full:
                with self.action_ocr_pending_lock:
                    self.action_ocr_pending_seats.discard(index)
                self.action_ocr_dropped += 1
            continue
            if "弃牌" in avatar_text and action == "waiting":
                action = "fold"
            bet = self._extract_bet(text)
            if bet == 0 and action in ("post_blind", "raise", "call"):
                numbers = [float(value) for value in re.findall(r"\d+(?:\.\d+)?", text)]
                bet = numbers[-1] if len(numbers) == 1 else None
            if action in ("raise", "call") and bet is None:
                continue
            chips = tracker.get("chips")
            if bet is not None and chips is not None and bet > chips * 1.05:
                continue
            if bet is not None and pot_after is not None and bet > max(50, pot_after * 8):
                continue
            observations.append({"index": index, "name": tracker.get("name", ""),
                                 "chips": tracker.get("chips"), "streetBet": bet,
                                 "action": action, "occupancy": "occupied"})
        if not observations:
            return events
        observations.sort(key=lambda seat: self._action_order_key(seat["index"]))
        _, events = self._update_action_state(observations, pot_after=pot_after)
        return events

    def _action_order_key(self, seat_index):
        dealer = self.hand_dealer_index
        count = len(TABLE_LAYOUTS[self.layout])
        if dealer is None:
            return seat_index
        start = (dealer + (3 if self.hand_state.get("street") == "preflop" else 1)) % count
        return (seat_index - start) % count

    def _append_action_candidate(self, event):
        if event.get("observedAt") is None:
            captured_at = getattr(self, "latest_frame_captured_at", None)
            event["observedAt"] = captured_at if captured_at is not None else time.time()
        event.setdefault("videoSecond", getattr(self, "recording_second", None))
        signature = (event.get("handId"), event.get("street"), event.get("seat"), event.get("action"))
        for item in reversed(self.action_candidates[-16:]):
            same = (item.get("handId"), item.get("street"), item.get("seat"), item.get("action")) == signature
            close = abs(float(item.get("videoSecond") or 0) - float(event.get("videoSecond") or 0)) < .75
            unresolved_amount = str(event.get("action", "")).endswith("_amount_unresolved")
            if same and (event.get("action") == "fold" or unresolved_amount or close):
                item["evidenceFrames"] = item.get("evidenceFrames", 1) + 1
                item["lastSeenSecond"] = event.get("videoSecond")
                signals = item.setdefault("evidenceSignals", {})
                first_avatar_text = (event.get("evidenceSignals", {}).get("avatarText") and
                                     not signals.get("avatarText"))
                signals.update({key: bool(signals.get(key) or value)
                                for key, value in event.get("evidenceSignals", {}).items()})
                if first_avatar_text:
                    item.update(observedAt=event.get("observedAt"),
                                videoSecond=event.get("videoSecond"),
                                frameSequence=event.get("frameSequence"),
                                firstRecognizedAt=event.get("recognizedAt", time.time()))
                if (event.get("action") == "fold" and item["evidenceFrames"] >= 3 and
                        signals.get("avatarText") and
                        self.formal_expected_seat == (event.get("seat") or 1) - 1 and
                        not item.get("promoted")):
                    promoted = dict(item)
                    promoted.pop("visualCandidate", None)
                    promoted.update(chainStatus="rule_confirmed", strategyEligible=True,
                                    confidence=.9, evidence="avatar_model+contrast_drop+action_order")
                    if self._append_action_event(promoted):
                        item["promoted"] = True
                        index = (event.get("seat") or 1) - 1
                        tracker = self.seat_trackers.get(index)
                        if tracker:
                            tracker["lastAction"] = "fold"
                        self.formal_expected_seat = self._next_opponent_seat(index)
                        self._promote_expected_fold_chain()
                return False
        event["chainStatus"] = "visual_candidate"
        event["strategyEligible"] = False
        event["evidenceFrames"] = 3 if event.get("evidenceSignals", {}).get("avatarText") else 1
        self.action_candidates.append(event)
        if event.get("action") == "fold" and event.get("evidenceSignals", {}).get("avatarText"):
            self._promote_expected_fold_chain()
            if not event.get("promoted"):
                event_second = (event.get("videoSecond") if event.get("videoSecond") is not None
                                else event.get("observedAt"))
                later_action = next((item for item in self.action_log
                                     if item.get("handId") == event.get("handId") and
                                     item.get("street") == event.get("street") and
                                     item.get("seat") != event.get("seat") and
                                     item.get("action") not in ("blind", "post_blind", "straddle") and
                                     event_second is not None and
                                     (item.get("videoSecond") if event.get("videoSecond") is not None
                                      else item.get("observedAt")) is not None and
                                     float(item.get("videoSecond") if event.get("videoSecond") is not None
                                           else item.get("observedAt")) >=
                                     float(event_second)), None)
                if later_action is not None:
                    expected_after_later_action = self.formal_expected_seat
                    promoted = dict(event)
                    promoted.pop("visualCandidate", None)
                    promoted.update(chainStatus="rule_confirmed", strategyEligible=True,
                                    confidence=.9,
                                    evidence="avatar_text+late_async_order_repair",
                                    inferred=True)
                    if self._append_action_event(promoted, resolve_prior=False):
                        event["promoted"] = True
                        tracker = self.seat_trackers.get((event.get("seat") or 1) - 1)
                        if tracker:
                            tracker["lastAction"] = "fold"
                        self.formal_expected_seat = expected_after_later_action
        return True

    def _promote_expected_fold_chain(self):
        if not hasattr(self, "action_candidates"):
            return
        current_second = getattr(self, "recording_second", None)
        terminal = {seat - 1 for seat in self.folded_seats}
        terminal.update((item.get("seat") or 1) - 1 for item in self.action_log
                        if item.get("handId") == self.hand_state.get("id") and
                        item.get("action") in ("fold", "allin"))
        selection = ActionEngine.select_fold_promotions(
            self.action_candidates, self.hand_state.get("id"),
            self.hand_state.get("street"), getattr(self, "formal_expected_seat", None),
            len(TABLE_LAYOUTS[self.layout]), self._current_hand_eligible_indices(),
            require_text=True, current_second=current_second, terminal=terminal)
        for candidate in selection["candidates"]:
            expected = (candidate.get("seat") or 1) - 1
            promoted = dict(candidate)
            promoted.pop("visualCandidate", None)
            promoted.update(chainStatus="rule_confirmed", strategyEligible=True,
                            confidence=.9,
                            evidence="avatar_text+consecutive_action_order")
            if not self._append_action_event(promoted, resolve_prior=False):
                return
            candidate["promoted"] = True
            tracker = self.seat_trackers.get(expected)
            if tracker:
                tracker["lastAction"] = "fold"
        if selection["candidates"]:
            self.formal_expected_seat = selection["nextExpected"]

    def _next_tracker_seat(self, seat_index):
        occupied = self._current_hand_eligible_indices()
        count = len(TABLE_LAYOUTS[self.layout])
        for offset in range(1, count + 1):
            candidate = (seat_index + offset) % count
            if not occupied or candidate in occupied:
                return candidate
        return (seat_index + 1) % count

    def _next_opponent_seat(self, seat_index):
        count = len(TABLE_LAYOUTS[self.layout])
        eligible = self._current_hand_eligible_indices()
        terminal = {seat - 1 for seat in self.folded_seats}
        terminal.update((item.get("seat") or 1) - 1 for item in self.action_log
                        if item.get("handId") == self.hand_state.get("id") and
                        item.get("action") in ("fold", "allin"))
        return HandStateLayer.next_actor(seat_index, count, eligible, terminal)

    def _current_hand_eligible_indices(self):
        return HandStateLayer.eligible_indices(
            self.hand_state.get("id"), self.hand_participants, self.seat_trackers)

    @staticmethod
    def _reconcile_hero_total_amount(displayed_total, prior_total, chips_before, chips_after):
        if (not isinstance(chips_before, (int, float)) or
                not isinstance(chips_after, (int, float)) or
                float(chips_before) <= float(chips_after) + .001):
            return displayed_total
        chip_increase = float(chips_before) - float(chips_after)
        chip_total = round(float(prior_total or 0) + chip_increase, 6)
        if (displayed_total in (None, 0) or
                abs(float(displayed_total) - chip_total) > max(.05, chip_increase * .15)):
            return chip_total
        return displayed_total

    def _infer_hero_action(self, hero, buttons):
        current_bet = float(hero.get("streetBet") or 0)
        current_chips = hero.get("chips")
        had_buttons = self._official_action_cluster(self.previous_buttons)
        action = None
        if had_buttons and not buttons and self._hero_turn_latched():
            return None
        if self._official_action_cluster(buttons) and not self._official_action_cluster(self.previous_buttons):
            self.hero_decision_chips = current_chips
        if self._official_action_cluster(buttons):
            self.hero_last_official_buttons = list(buttons)
            self.hero_last_official_chips = current_chips
            self.hero_last_official_second = getattr(self, "recording_second", None)
        if had_buttons and not buttons:
            if time.time() - self.last_street_change_at < 2.0:
                self.previous_buttons = buttons
                return None
            self.pending_hero_buttons = list(self.previous_buttons)
            self.pending_hero_chips = self.hero_decision_chips if isinstance(self.hero_decision_chips, (int, float)) else self.previous_hero_chips
            self.pending_hero_started = time.time()
            self.pending_hero_second = getattr(self, "recording_second", None)
            self.pending_hero_frames = 0
            self.pending_hero_hand_id = self.hand_state.get("id")
            self.pending_hero_street = self.hand_state.get("street")
        if self.pending_hero_buttons and not buttons:
            self.pending_hero_frames += 1
        current_second = getattr(self, "recording_second", None)
        pending_age = (current_second - self.pending_hero_second
                       if current_second is not None and self.pending_hero_second is not None
                       else time.time() - self.pending_hero_started)
        pending = bool(self.pending_hero_buttons and pending_age <= 1.5)
        if pending and not buttons:
            bet_invested = max(0, current_bet - self.previous_hero_bet)
            chip_invested = max(0, self.pending_hero_chips - current_chips) if (
                isinstance(self.pending_hero_chips, (int, float)) and isinstance(current_chips, (int, float))) else 0
            reconciled_total = self._reconcile_hero_total_amount(
                current_bet if bet_invested > 0 else None,
                self.previous_hero_bet, self.pending_hero_chips, current_chips)
            invested = (max(0.0, float(reconciled_total) - self.previous_hero_bet)
                        if reconciled_total not in (None, 0) else chip_invested)
            if invested > 0:
                previous_call = next((button for button in self.pending_hero_buttons if button["kind"] == "call"), None)
                call_value = previous_call.get("value") if previous_call else None
                if isinstance(current_chips, (int, float)) and current_chips <= .01:
                    action = {"action": "allin", "amount": invested, "confidence": .9}
                elif isinstance(call_value, (int, float)) and abs(invested - call_value) <= max(.05, call_value * .12):
                    action = {"action": "call", "amount": invested, "confidence": .75}
                else:
                    action = {"action": "raise", "amount": invested, "confidence": .68}
                action["totalAmount"] = round(self.previous_hero_bet + invested, 6)
                action["chipsBefore"] = self.pending_hero_chips
                action["observedAt"] = self.pending_hero_started
                action["observedSecond"] = self.pending_hero_second
                self.pending_hero_buttons = []
                self.hero_decision_chips = None
            else:
                fold_available = any(button["kind"] == "fold" for button in self.pending_hero_buttons)
                check_available = any(button["kind"] == "check" for button in self.pending_hero_buttons)
                if pending_age >= .4 and check_available and not fold_available:
                    action = {"action": "check", "amount": 0, "confidence": .65}
                    self.pending_hero_buttons = []
                    self.hero_decision_chips = None
                elif pending_age > 1.5:
                    self.pending_hero_buttons = []
                    self.hero_decision_chips = None
        if (action is None and not buttons and self.hero_last_official_buttons and
                isinstance(self.hero_last_official_chips, (int, float)) and
                isinstance(current_chips, (int, float)) and current_chips < self.hero_last_official_chips - .01):
            invested = self.hero_last_official_chips - current_chips
            call_button = next((button for button in self.hero_last_official_buttons if button["kind"] == "call"), None)
            call_value = call_button.get("value") if call_button else None
            kind = ("allin" if current_chips <= .01 else
                    "call" if isinstance(call_value, (int, float)) and
                    abs(invested - call_value) <= max(.05, call_value * .12) else "raise")
            action = {"action": kind, "amount": invested, "confidence": .72}
            action["totalAmount"] = round(self.previous_hero_bet + invested, 6)
            action["chipsBefore"] = self.hero_last_official_chips
            action["observedAt"] = (self.pending_hero_started
                                    if self.pending_hero_started is not None else time.time())
            action["observedSecond"] = self.pending_hero_second if self.pending_hero_second is not None else self.hero_last_official_second
            self.hero_last_official_buttons = []
            self.hero_last_official_chips = None
        self.previous_hero_bet = current_bet
        self.previous_hero_chips = current_chips
        self.previous_buttons = buttons
        return action

    def show_advice(self, payload):
        if self.overlay is not None:
            self.overlay.update(self._overlay_bbox(), "", None, True, self.border_color)
        return {"shown": False, "arrowShown": False, "reason": "牌桌只显示采集边框"}

    def _recognize_action_buttons(self, frame, ocr_items):
        height, width = frame.shape[:2]
        region_top = int(height * .62)
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        blue_mask = cv2.inRange(hsv, np.array([85, 70, 60]), np.array([135, 255, 255]))
        red_mask = cv2.inRange(hsv, np.array([0, 80, 70]), np.array([12, 255, 255])) | cv2.inRange(hsv, np.array([165, 80, 70]), np.array([180, 255, 255]))
        green_mask = cv2.inRange(hsv, np.array([35, 45, 35]), np.array([85, 255, 220]))
        gray_mask = cv2.inRange(hsv, np.array([0, 0, 45]), np.array([180, 65, 205]))
        buttons = []
        for color, mask in (("blue", blue_mask), ("red", red_mask), ("green", green_mask), ("gray", gray_mask)):
            contours, _ = cv2.findContours(mask[region_top:], cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                x, y, button_width, button_height = cv2.boundingRect(contour)
                y += region_top
                if button_width < width * .075 or button_height < width * .075:
                    continue
                cx, cy = x + button_width / 2, y + button_height / 2
                relative_x, relative_y = cx / width, cy / height
                if not (.12 <= relative_x <= .88 and .62 <= relative_y <= .88):
                    continue
                nearby = [item for item in ocr_items if x - 12 <= item["cx"] <= x + button_width + 12 and y - 12 <= item["cy"] <= y + button_height + 12]
                text = " ".join(item["text"] for item in nearby).strip()
                kind, value = self._classify_button(text, color, relative_x, relative_y)
                if kind:
                    buttons.append({"kind": kind, "value": value, "text": text, "color": color, "x": round(cx / width, 4), "y": round(cy / height, 4), "confidence": round(sum(item["confidence"] for item in nearby) / len(nearby), 3) if nearby else .55})
        for item in ocr_items:
            if item["cy"] < height * .62:
                continue
            normalized = item["text"].strip().lower()
            mapping = {"1/3": 1 / 3, "1/2": .5, "2/3": 2 / 3, "1.2": 1.2, "1": 1.0}
            if normalized in mapping:
                buttons.append({"kind": "quick_bet", "value": mapping[normalized], "text": item["text"], "x": round(item["cx"] / width, 4), "y": round(item["cy"] / height, 4), "confidence": round(item["confidence"], 3)})
        buttons = self._deduplicate_buttons(buttons)
        quick_values = {round(button["value"], 3) for button in buttons if button["kind"] == "quick_bet"}
        kinds = {button["kind"] for button in buttons}
        has_action_cluster = any(button["kind"] in ("custom_raise", "call") for button in buttons) or len(quick_values) >= 3 or ({"fold", "check"}.issubset(kinds) and any(button.get("color") == "red" for button in buttons))
        if not has_action_cluster:
            return []
        if {round(1 / 3, 3), .5, round(2 / 3, 3), 1.2}.issubset(quick_values) and 1.0 not in quick_values:
            buttons.append({"kind": "quick_bet", "value": 1.0, "text": "1", "x": .666, "y": .666, "confidence": .72})
            buttons.sort(key=lambda item: item["x"])
        return buttons

    def _recognize_action_buttons_fast(self, frame):
        height, width = frame.shape[:2]
        top = int(height * .61)
        crop = frame[top:int(height * .91)]
        items = self._ocr_items(crop)
        for item in items:
            item["cy"] += top
        return self._recognize_action_buttons(frame, items)

    def _recognize_action_buttons_visual(self, frame):
        height, width = frame.shape[:2]
        region_top = int(height * .70)
        region_bottom = int(height * .91)
        hsv = cv2.cvtColor(frame[region_top:region_bottom], cv2.COLOR_BGR2HSV)
        masks = {
            "blue": cv2.inRange(hsv, np.array([85, 70, 60]), np.array([135, 255, 255])),
            "red": cv2.inRange(hsv, np.array([0, 80, 70]), np.array([12, 255, 255])) |
                   cv2.inRange(hsv, np.array([165, 80, 70]), np.array([180, 255, 255])),
            "green": cv2.inRange(hsv, np.array([35, 45, 35]), np.array([85, 255, 220])),
            "gray": cv2.inRange(hsv, np.array([0, 0, 45]), np.array([180, 65, 205])),
        }
        candidates = []
        for color, mask in masks.items():
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                x, y, button_width, button_height = cv2.boundingRect(contour)
                y += region_top
                if button_width < width * .075 or button_height < width * .075:
                    continue
                cx, cy = x + button_width / 2, y + button_height / 2
                relative_x, relative_y = cx / width, cy / height
                if not (.12 <= relative_x <= .88 and .72 <= relative_y <= .88):
                    continue
                kind = None
                if color == "red" and relative_x <= .48:
                    kind = "fold"
                elif relative_x > .58 and color == "blue":
                    kind = "call"
                elif (relative_x > .58 and color in ("green", "gray") and
                      self._hero_action_countdown_visible(frame)):
                    kind = "check"
                elif .40 <= relative_x <= .65 and color == "blue":
                    kind = "custom_raise"
                if kind:
                    candidates.append({"kind": kind, "value": None, "text": "", "color": color,
                                       "x": round(relative_x, 4), "y": round(relative_y, 4), "confidence": .9})
        candidates = self._deduplicate_buttons(candidates)
        kinds = {button["kind"] for button in candidates}
        if ({"fold", "custom_raise"}.issubset(kinds) and
                not kinds.intersection({"call", "check"})):
            center_x, center_y = int(width * .738), int(height * .8104)
            crop = frame[
                max(0, center_y - int(height * .018)):min(height, center_y + int(height * .018)),
                max(0, center_x - int(width * .047)):min(width, center_x + int(width * .047)),
            ]
            fixed_hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
            fixed_green = cv2.inRange(
                fixed_hsv, np.array([35, 45, 35]), np.array([85, 255, 220]))
            fixed_green_ratio = float(np.mean(fixed_green > 0))
            if fixed_green_ratio >= .65:
                candidates.append({
                    "kind": "check", "value": None, "text": "fixed_green_slot", "color": "green",
                    "x": .738, "y": .8104, "confidence": .92,
                })
            else:
                gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
                gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
                text, confidence = self._button_ocr_line(gray)
                normalized = re.sub(r"\s+", "", str(text).lower())
                if (float(confidence or 0) >= .85 and
                        any(word in normalized for word in ACTION_TEXT_WORDS["check"])):
                    candidates.append({
                        "kind": "check", "value": None, "text": text, "color": "green",
                        "x": .738, "y": .8104, "confidence": round(float(confidence), 3),
                    })
        return self._deduplicate_buttons(candidates)

    @staticmethod
    def _hero_action_countdown_visible(frame):
        height, width = frame.shape[:2]
        region = frame[int(height * .70):int(height * .78), int(width * .18):int(width * .34)]
        if region.size == 0:
            return False
        hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
        white = (hsv[:, :, 1] < 70) & (hsv[:, :, 2] > 170)
        yellow = ((hsv[:, :, 0] >= 18) & (hsv[:, :, 0] <= 40) &
                  (hsv[:, :, 1] > 90) & (hsv[:, :, 2] > 150))
        return float(np.mean(white)) >= .006 and float(np.mean(yellow)) >= .0008

    @staticmethod
    def _detect_special_scene(frame):
        return RecognitionLayer.detect_special_scene(frame)

    def _recognize_visual_button_values(self, frame, buttons):
        height, width = frame.shape[:2]
        result = []
        for button in buttons:
            item = dict(button)
            if item["kind"] == "call":
                center_x, center_y = int(item["x"] * width), int(item["y"] * height)
                crop = frame[max(0, center_y - int(height * .018)):min(height, center_y + int(height * .018)),
                             max(0, center_x - int(width * .047)):min(width, center_x + int(width * .047))]
                gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
                gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
                text, confidence = self._button_ocr_line(cv2.resize(
                    gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC))
                value = self._extract_number(text)
                confidence = float(confidence or 0)
                prior_confidence = float(item.get("confidence") or 0)
                normalized = re.sub(r"\s+", "", str(text).lower())
                if any(word.replace(" ", "") in normalized
                       for word in ACTION_TEXT_WORDS["allin"]):
                    item.update({"text": text, "value": "allin", "allinCall": True,
                                 "confidence": round(max(prior_confidence, confidence), 3),
                                 "ocrConfidence": round(confidence, 3)})
                elif any(word in normalized for word in ("让牌", "过牌", "check", "횻탬")):
                    item.update({"kind": "check", "text": text, "value": None,
                                 "confidence": round(max(prior_confidence, confidence), 3)})
                else:
                    item.update({"text": text, "value": value,
                                 "confidence": round(max(prior_confidence, confidence), 3),
                                 "ocrConfidence": round(confidence, 3)})
            result.append(item)
        return result


    @staticmethod
    def _center_ocr_crop(frame):
        height, width = frame.shape[:2]
        return frame[int(height * .20):int(height * .34), int(width * .32):int(width * .68)]

    def _enqueue_center_ocr(self, frame, captured_at, frame_sequence, capture_context=None):
        crop = self._center_ocr_crop(frame)
        context = dict(capture_context or self._new_capture_context(
            captured_at, frame_sequence, self.latest_frame_video_second))
        image_signature = hashlib.blake2s(
            cv2.resize(crop, (96, 32), interpolation=cv2.INTER_AREA).tobytes(),
            digest_size=8).hexdigest()
        signature = ":".join(str(context.get(key)) for key in (
            "runtimeId", "tableSession", "handId", "street")) + ":" + image_signature
        if signature in self.center_ocr_cache or signature == self.center_ocr_pending_hash:
            return signature
        try:
            self.center_ocr_queue.put_nowait(
                (signature, crop.copy(), frame.shape[:2], captured_at, frame_sequence, context))
            self.center_ocr_pending_hash = signature
        except queue.Full:
            pass
        return signature

    def _center_ocr_loop(self):
        worker_ocr = RapidOCR(intra_op_num_threads=1, inter_op_num_threads=1)
        while True:
            signature, crop, frame_shape, captured_at, frame_sequence, context = self.center_ocr_queue.get()
            try:
                scale = 2.0
                recognized, _ = worker_ocr(cv2.resize(crop, None, fx=scale, fy=scale,
                                                       interpolation=cv2.INTER_CUBIC))
                height, width = frame_shape
                offset_x, offset_y = width * .32, height * .20
                values = []
                for item in recognized or []:
                    box, text, confidence = item[0], str(item[1]), float(item[2])
                    number = self._extract_number(text)
                    if number is None:
                        continue
                    center_x = sum(point[0] for point in box) / (4 * scale)
                    center_y = sum(point[1] for point in box) / (4 * scale)
                    values.append({"value": number, "x": round((offset_x + center_x) / width, 4),
                                   "y": round((offset_y + center_y) / height, 4),
                                   "confidence": round(confidence, 3), "text": text})
                candidates = [item for item in values if .242 <= item["y"] <= .272 and .38 <= item["x"] <= .62]
                best = min(candidates, key=lambda item: abs(item["y"] - .257), default=None)
                self.center_ocr_results.put({"hash": signature, "pot": best["value"] if best else None,
                                             "confidence": best["confidence"] if best else 0.0,
                                             "potText": best["text"] if best else "",
                                             "values": values, "capturedAt": captured_at,
                                             "frameSequence": frame_sequence,
                                             "runtimeId": context.get("runtimeId"),
                                             "tableSession": context.get("tableSession"),
                                             "handId": context.get("handId"),
                                             "street": context.get("street")})
            finally:
                self.center_ocr_queue.task_done()

    @staticmethod
    def _peek_slot_box(width, height):
        return Api._reviewed_slot_box((195, 1450, 315, 1560), width, height)

    @staticmethod
    def _peek_slot_candidate(frame):
        height, width = frame.shape[:2]
        x1, y1, x2, y2 = Api._peek_slot_box(width, height)
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return False
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        return float(gray.std()) >= 34 and float(np.mean(gray > 180)) >= .07

    def _enqueue_peek_job(self, job):
        try:
            self.peek_queue.put_nowait(job)
            return True
        except queue.Full:
            pass
        try:
            queued = self.peek_queue.get_nowait()
            self.peek_queue.task_done()
        except queue.Empty:
            return False
        if queued.get("kind") == "button" and job.get("kind") == "reveal":
            try:
                self.peek_queue.put_nowait(queued)
            except queue.Full:
                pass
            return False
        try:
            self.peek_queue.put_nowait(job)
            return True
        except queue.Full:
            return False

    def _observe_peek_slot(self, frame, captured_at, frame_sequence):
        candidate = self._peek_slot_candidate(frame)
        now = captured_at if isinstance(captured_at, (int, float)) else time.time()
        if candidate and not self.peek_candidate_visible:
            self.peek_epoch += 1
            self.peek_candidate_started_at = now
            self.peek_candidate_observations = 0
            self.peek_candidate_confirmed = False
            self.peek_reveal_deadline = 0.0
            self.peek_reveal_epoch = self.peek_epoch
            self.peek_reveal_started_at = 0.0
            self.peek_reveal_votes = {}
            self.peek_reveal_observation_count = 0
            self.peek_state.update(available=False, triggered=False,
                                   cost=None,
                                   revealedCards=[], source=None,
                                   observedAt=None, confirmedAt=None)
        if candidate:
            self.peek_candidate_observations += 1
        if candidate and (not self.peek_candidate_visible or now - self.peek_last_probe_at >= .25):
            x1, y1, x2, y2 = self._peek_slot_box(frame.shape[1], frame.shape[0])
            self._enqueue_peek_job({"kind": "button", "crop": frame[y1:y2, x1:x2].copy(),
                                    "capturedAt": now, "frameSequence": frame_sequence,
                                    "epoch": self.peek_epoch})
            self.peek_last_probe_at = now
        if self.peek_candidate_visible and not candidate:
            if (self.peek_candidate_observations >= 2 and
                    now - self.peek_candidate_started_at >= .08):
                self.peek_candidate_confirmed = True
            self.peek_reveal_epoch = self.peek_epoch
            self.peek_reveal_started_at = now
            self.peek_reveal_deadline = now + 3.0
            self.peek_reveal_votes = {}
            self.peek_reveal_observation_count = 0
        if self.peek_reveal_deadline >= now and not candidate and now - self.peek_last_probe_at >= .12:
            self._enqueue_peek_job({"kind": "reveal", "frame": frame.copy(),
                                    "capturedAt": now, "frameSequence": frame_sequence,
                                    "epoch": self.peek_reveal_epoch})
            self.peek_last_probe_at = now
        if self.peek_reveal_deadline and now > self.peek_reveal_deadline:
            self.peek_state["available"] = False
        self.peek_candidate_visible = candidate

    def _commit_peek_reveal(self, result, revealed):
        if self.peek_state.get("triggered"):
            return
        cost = self.peek_state.get("cost")
        self.peek_state.update(available=False, triggered=True,
                               usageCount=self.peek_state["usageCount"] + 1,
                               totalCost=round(self.peek_state["totalCost"] + float(cost or 0), 6),
                               revealedCards=revealed, source="peek",
                               observedAt=result.get("capturedAt"), confirmedAt=time.time())
        self.peek_reveal_deadline = 0.0
        self.peek_reveal_started_at = 0.0
        accepted = self.history_store.observe_revealed_cards(
            self.hand_state.get("id", 0), self.peek_state["revealedCards"], "peek")
        if accepted:
            self._schedule_profile_calibration()
        self._append_bounded_audit(
            self.peek_audit_file,
            {"time": time.time(), "handId": self.hand_state.get("id", 0),
             **self.peek_state})

    def _peek_recognition_loop(self):
        worker_ocr = None
        while True:
            job = self.peek_queue.get()
            try:
                if job["kind"] == "button":
                    if worker_ocr is None:
                        worker_ocr = RapidOCR(intra_op_num_threads=1, inter_op_num_threads=1)
                    enlarged = cv2.resize(job["crop"], None, fx=2.5, fy=2.5,
                                           interpolation=cv2.INTER_CUBIC)
                    result, _ = worker_ocr(enlarged)
                    text = " ".join(str(item[1]) for item in result or [])
                    normalized = re.sub(r"\s+", "", text).lower()
                    has_label = ("偷偷看" in normalized or
                                 ("偷" in normalized and "看" in normalized))
                    cost = self._extract_number(text)
                    if has_label or (cost is not None and 0 < cost <= 1):
                        self.peek_results.put({"kind": "available", "cost": cost,
                                               "text": text, "capturedAt": job["capturedAt"],
                                               "frameSequence": job["frameSequence"],
                                               "epoch": job.get("epoch", 0),
                                               "visualOnly": not has_label})
                    else:
                        self._record_peek_diagnostic("button_ocr_rejected", job, text=text)
                else:
                    cards = self._recognize_revealed_opponent_cards(job["frame"], fast_only=True)
                    if cards:
                        self.peek_results.put({"kind": "reveal_observation", "revealedCards": cards,
                                               "capturedAt": job["capturedAt"],
                                               "frameSequence": job["frameSequence"],
                                               "epoch": job.get("epoch", 0)})
                    else:
                        self._record_peek_diagnostic("reveal_cards_rejected", job,
                                                     recognizedSeats=len(cards), cards=cards)
            finally:
                self.peek_queue.task_done()

    def _record_peek_diagnostic(self, reason, job, **details):
        try:
            self._append_bounded_audit(
                self.peek_diagnostic_file,
                {"time": time.time(), "reason": reason,
                 "capturedAt": job.get("capturedAt"),
                 "frameSequence": job.get("frameSequence"), **details})
        except OSError:
            pass

    def _recognize_revealed_opponent_cards(self, frame, fast_only=False):
        source_frame = frame
        source_height, source_width = source_frame.shape[:2]
        if source_frame.shape[:2] != (1920, 888):
            frame = cv2.resize(source_frame, (888, 1920), interpolation=cv2.INTER_CUBIC)
        height, width = frame.shape[:2]
        hero_index = 4 if self.layout == "8max" else 3
        revealed = []
        for index, (center_x, center_y) in enumerate(TABLE_LAYOUTS[self.layout]):
            if index == hero_index:
                continue
            reference_box = (center_x * 888 - 100, center_y * 1920 - 75,
                             center_x * 888 + 100, center_y * 1920 + 85)
            x1, y1, x2, y2 = self._reviewed_slot_box(reference_box, width, height)
            crop_x1, crop_y1 = max(0, x1), max(0, y1)
            crop_x2, crop_y2 = min(width, x2), min(height, y2)
            crop = frame[crop_y1:crop_y2, crop_x1:crop_x2]
            if crop.size == 0:
                continue
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            mask = cv2.inRange(gray, 150, 255)
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            pairs = []
            for contour in contours:
                x, y, pair_width, pair_height = cv2.boundingRect(contour)
                ratio = pair_width / max(pair_height, 1)
                if pair_height >= crop.shape[0] * .55 and 1.05 <= ratio <= 1.7:
                    pairs.append((pair_width * pair_height, x, y, pair_width, pair_height))
            if not pairs:
                continue
            _, x, y, pair_width, pair_height = max(pairs)
            cards = []
            for card_index in range(2):
                left = x + round(pair_width * card_index / 2)
                right = x + round(pair_width * (card_index + 1) / 2)
                global_left, global_right = crop_x1 + left, crop_x1 + right
                global_top, global_bottom = crop_y1 + y, crop_y1 + y + pair_height
                source_left = max(0, round(global_left * source_width / width))
                source_right = min(source_width, round(global_right * source_width / width))
                source_top = max(0, round(global_top * source_height / height))
                source_bottom = min(source_height, round(global_bottom * source_height / height))
                card_crop = source_frame[source_top:source_bottom, source_left:source_right]
                card = self._read_revealed_card_multiscale(card_crop, allow_ocr=not fast_only)
                if card is None and right - left > 16:
                    trim_left = min(source_right, source_left + max(1, round(3 * source_width / width)))
                    trim_right = max(trim_left + 1, source_right - max(1, round(8 * source_width / width)))
                    trimmed = source_frame[source_top:source_bottom, trim_left:trim_right]
                    card = self._read_revealed_card_multiscale(trimmed, allow_ocr=not fast_only)
                if card:
                    cards.append(card)
            if len(cards) == 2 and len(set(cards)) == 2:
                tracker = self.seat_trackers.get(index, {})
                revealed.append({"seat": index + 1, "name": tracker.get("name", ""),
                                 "cards": cards})
        all_cards = [card for item in revealed for card in item["cards"]]
        known_cards = set(self.card_published.get("heroCards", [])) | set(
            self.card_published.get("boardCards", []))
        if len(all_cards) != len(set(all_cards)) or known_cards.intersection(all_cards):
            return []
        return revealed

    def _read_revealed_card_multiscale(self, card_crop, allow_ocr=True):
        if card_crop.size == 0:
            return None
        rank = self._match_rank_template(card_crop)
        suit = self._card_suit(card_crop)
        if rank and suit:
            return rank + suit
        fast_votes = []
        for trim in (1, 2, 3, 4, 6, 8):
            if card_crop.shape[1] - trim * 2 < 24:
                continue
            sample = card_crop[:, trim:card_crop.shape[1] - trim or None]
            rank = self._match_rank_template(sample)
            suit = self._card_suit(sample)
            if rank and suit:
                fast_votes.append(rank + suit)
        if fast_votes:
            best, count = Counter(fast_votes).most_common(1)[0]
            if count >= 2 or not allow_ocr:
                return best
        if not allow_ocr:
            return None
        scale = min(card_crop.shape[0] / 120, card_crop.shape[1] / 85)
        factors = (1.0,) if scale >= .9 else (1.5, 2.0, 3.5)
        votes = []
        for factor in factors:
            sample = card_crop if factor == 1 else cv2.resize(
                card_crop, None, fx=factor, fy=factor, interpolation=cv2.INTER_CUBIC)
            parsed = self._read_card(sample)
            template_rank = self._match_rank_template(sample)
            suit = self._card_suit(sample)
            if template_rank and suit:
                votes.extend([template_rank + suit, template_rank + suit])
            if parsed:
                votes.append(parsed)
        counts = Counter(votes)
        best, count = max(counts.items(), key=lambda item: item[1], default=(None, 0))
        return best if count >= 2 else None

    def _drain_peek_results(self):
        while True:
            try:
                result = self.peek_results.get_nowait()
            except queue.Empty:
                return
            now = time.time()
            if result["kind"] == "available":
                if result.get("epoch", self.peek_epoch) != self.peek_epoch:
                    self._record_peek_diagnostic("stale_button_result", result)
                    continue
                self.peek_candidate_confirmed = True
                self.peek_state.update(available=not bool(self.peek_reveal_started_at),
                                       triggered=False, cost=result.get("cost"),
                                       revealedCards=[], source=None,
                                       observedAt=result.get("capturedAt"), confirmedAt=now)
            elif result["kind"] == "triggered":
                if self.peek_candidate_confirmed and not self.peek_state.get("triggered"):
                    self._commit_peek_reveal(result, result.get("revealedCards", []))
            elif result["kind"] == "reveal_observation":
                if (not self.peek_candidate_confirmed or
                        result.get("epoch", self.peek_epoch) != self.peek_reveal_epoch or
                        not self.peek_reveal_deadline or
                        result.get("capturedAt", 0) < self.peek_reveal_started_at or
                        result.get("capturedAt", 0) > self.peek_reveal_deadline + .25):
                    self._record_peek_diagnostic("reveal_observation_rejected", result,
                                                 recognizedSeats=len(result.get("revealedCards", [])))
                    continue
                self.peek_reveal_observation_count += 1
                for item in result.get("revealedCards", []):
                    seat = item.get("seat")
                    cards = tuple(item.get("cards") or ())
                    if not isinstance(seat, int) or len(cards) != 2 or len(set(cards)) != 2:
                        continue
                    votes = self.peek_reveal_votes.setdefault(seat, Counter())
                    votes[cards] += 1
                stable = []
                for seat, votes in self.peek_reveal_votes.items():
                    cards, count = votes.most_common(1)[0]
                    if count >= 2:
                        latest = next((item for item in result.get("revealedCards", [])
                                       if item.get("seat") == seat and
                                       tuple(item.get("cards") or ()) == cards), None)
                        stable.append(latest or {"seat": seat, "name": "", "cards": list(cards)})
                current = result.get("revealedCards", [])
                if len(current) >= 3:
                    self._commit_peek_reveal(result, current)
                elif len(stable) >= 1 and self.peek_reveal_observation_count >= 2:
                    self._commit_peek_reveal(result, stable)
            with self.state_lock:
                self.cached_state = dict(self.cached_state or {})
                self.cached_state["peek"] = dict(self.peek_state)

    def _drain_center_ocr_results(self):
        while True:
            try:
                result = self.center_ocr_results.get_nowait()
            except queue.Empty:
                return
            if self.center_ocr_pending_hash == result.get("hash"):
                self.center_ocr_pending_hash = None
            if (result.get("runtimeId") != self.runtime_id or
                    result.get("tableSession") != self.table_session or
                    result.get("handId") != self.hand_state.get("id") or
                    result.get("street") != self.hand_state.get("street")):
                continue
            result = self._validate_center_pot_result(result)
            self.center_ocr_cache[result["hash"]] = result
            while len(self.center_ocr_cache) > 8:
                self.center_ocr_cache.pop(next(iter(self.center_ocr_cache)))
            if result.get("pot") is not None:
                self.fields.commit("pot", result["pot"], result["confidence"], "center_ocr",
                                   result["confidence"] >= .65)

    def _validate_center_pot_result(self, result):
        value = result.get("pot")
        if not isinstance(value, (int, float)):
            return result
        field = self.fields.snapshot().get("pot", {})
        previous = field.get("value") if not field.get("stale", True) else None
        if not isinstance(previous, (int, float)):
            previous = self.hand_state.get("pot")
        if not isinstance(previous, (int, float)):
            self.center_pot_candidate = None
            return result
        tolerance = max(.01, abs(float(previous)) * .002)
        if float(value) < float(previous) - tolerance:
            rejected = dict(result)
            rejected.update(pot=None, confidence=0.0,
                            potRejectedReason="pot_decreased_within_same_hand_street")
            return rejected
        decimal_jump = any(
            abs(float(value) - float(previous) * ratio) <= tolerance * ratio
            for ratio in (10, 100, 1000))
        if not decimal_jump:
            self.center_pot_candidate = None
            return result
        identity = (result.get("runtimeId"), result.get("tableSession"),
                    result.get("handId"), result.get("street"), round(float(value), 3))
        prior = self.center_pot_candidate
        if (prior and prior["identity"] == identity and
                prior["frameSequence"] != result.get("frameSequence")):
            self.center_pot_candidate = None
            return result
        self.center_pot_candidate = {
            "identity": identity, "frameSequence": result.get("frameSequence")}
        rejected = dict(result)
        rejected.update(pot=None, confidence=0.0,
                        potRejectedReason="decimal_shift_requires_cross_frame_confirmation")
        return rejected

    def _confirmed_ledger_call_amount(self, hero_index):
        hand_id = self.hand_state.get("id")
        street = self.hand_state.get("street")
        investments = ("blind", "post_blind", "straddle", "call", "bet", "raise", "reraise", "allin")
        events = [item for item in self.action_log
                  if item.get("handId") == hand_id and item.get("street") == street and
                  item.get("action") in investments and isinstance(item.get("amount"), (int, float)) and
                  not item.get("orderConflict") and item.get("strategyEligible", True)]
        opponents = [item for item in events if item.get("seat") != hero_index + 1]
        if not opponents:
            return None
        highest = max(float(item["amount"]) for item in opponents)
        highest_sources = [item for item in opponents if abs(float(item["amount"]) - highest) <= .001]
        if max((float(item.get("confidence") or 0) for item in highest_sources), default=0) < .85:
            return None
        hero_events = [item for item in events if item.get("seat") == hero_index + 1]
        hero_invested = max((float(item["amount"]) for item in hero_events), default=0.0)
        return round(max(0.0, highest - hero_invested), 6)

    def _recognize_pot(self, frame):
        return self._recognize_center_amounts(frame)[0]

    def _recognize_center_amounts(self, frame, wait_for_ocr=True):
        height, width = frame.shape[:2]
        x1, y1 = int(width * .32), int(height * .20)
        crop = frame[y1:int(height * .34), x1:int(width * .68)]
        items = self._ocr_items(cv2.resize(crop, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC), wait=wait_for_ocr)
        values = []
        for item in items:
            value = self._extract_number(item["text"])
            if value is not None:
                values.append({"value": value, "x": round((x1 + item["cx"] / 2) / width, 4),
                               "y": round((y1 + item["cy"] / 2) / height, 4),
                               "confidence": round(item["confidence"], 3), "text": item["text"]})
        candidates = [item for item in values if .242 <= item["y"] <= .272 and .38 <= item["x"] <= .62]
        previous = self.hand_state.get("pot")
        if previous is not None:
            candidates = [item for item in candidates if item["value"] <= max(previous * 3, previous + 200)]
        best = min(candidates, key=lambda item: abs(item["y"] - .257), default=None)
        return (best["value"] if best else None, best["confidence"] if best else 0.0, values)

    @staticmethod
    def _classify_center_amounts(values):
        bands = {"实时总底池": (.242, .272), "上一阶段结算底池": (.273, .305), "额外结算金额": (.306, .338)}
        result = {}
        for label, (top, bottom) in bands.items():
            candidates = [item for item in values if top <= item["y"] <= bottom and .36 <= item["x"] <= .64]
            if candidates:
                item = max(candidates, key=lambda value: value["confidence"])
                result[label] = {"value": item["value"], "confidence": item["confidence"]}
        return result

    def _observe_dealer_index(self, frame, ocr_items=()):
        height, width = frame.shape[:2]
        marker_matches = []
        for item in ocr_items:
            if item["text"].strip().upper() != "D" or float(item.get("confidence") or 0) < .65:
                continue
            for index in range(len(TABLE_LAYOUTS[self.layout])):
                box = self._dealer_slot_box(index, width, height)
                if box and box[0] <= item["cx"] <= box[2] and box[1] <= item["cy"] <= box[3]:
                    marker_matches.append((float(item["confidence"]), index))
        if marker_matches:
            marker_matches.sort(reverse=True)
            if len(marker_matches) == 1 or marker_matches[0][0] - marker_matches[1][0] >= .08:
                return marker_matches[0][1]
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        anchor_scores = []
        for index, (anchor_x, anchor_y) in enumerate(DEALER_ANCHORS[self.layout]):
            box = self._dealer_slot_box(index, width, height)
            cx, cy = int(anchor_x * width), int(anchor_y * height)
            if not box or not (box[0] <= cx <= box[2] and box[1] <= cy <= box[3]):
                continue
            radius = max(10, int(width * .029))
            patch = hsv[max(0, cy - radius):min(height, cy + radius),
                        max(0, cx - radius):min(width, cx + radius)]
            if patch.size:
                white_ratio = float(np.mean((patch[:, :, 1] < 120) & (patch[:, :, 2] > 180)))
                dark_ratio = float(np.mean(patch[:, :, 2] < 90))
                anchor_scores.append((white_ratio + dark_ratio * .35, white_ratio, dark_ratio, index))
        best = max(anchor_scores, default=(0, 0, 0, None))
        if best[1] >= .20 and .035 <= best[2] <= .30:
            return best[3]
        bright = cv2.inRange(hsv, np.array([0, 0, 185]), np.array([180, 85, 255]))
        count, _, stats, centroids = cv2.connectedComponentsWithStats(bright)
        candidates = []
        expected_width, expected_height = width * .038, height * .018
        for component in range(1, count):
            x, y, box_width, box_height, area = stats[component]
            if not (.55 * expected_width <= box_width <= 1.55 * expected_width and
                    .55 * expected_height <= box_height <= 1.55 * expected_height and
                    .65 <= box_width / max(box_height, 1) <= 1.45):
                continue
            fill = area / max(box_width * box_height, 1)
            crop = frame[y:y + box_height, x:x + box_width]
            dark_ratio = float(np.mean(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) < 90))
            if not (.28 <= fill <= .82 and .04 <= dark_ratio <= .42):
                continue
            center_x, center_y = centroids[component]
            for index in range(len(TABLE_LAYOUTS[self.layout])):
                slot = self._dealer_slot_box(index, width, height)
                if slot and slot[0] <= center_x <= slot[2] and slot[1] <= center_y <= slot[3]:
                    candidates.append((fill + dark_ratio, index))
        candidates.sort(reverse=True)
        if not candidates or (len(candidates) > 1 and candidates[0][0] - candidates[1][0] < .05):
            return None
        return candidates[0][1]

    def _detect_dealer_index(self, frame, ocr_items=()):
        observed = self._observe_dealer_index(frame, ocr_items)
        if observed is None:
            return self.last_dealer_index
        self.last_dealer_index = observed
        self.pending_dealer_index, self.pending_dealer_frames = None, 0
        return self.last_dealer_index

    def _hero_position(self, hero_index, dealer_index, players):
        if dealer_index is None:
            return "unknown"
        seats = len(TABLE_LAYOUTS[self.layout])
        distance = (hero_index - dealer_index) % seats
        if distance == 0:
            return "late"
        if distance in (1, 2):
            return "blind"
        remaining = max(1, players - 3)
        return "early" if distance <= max(3, remaining // 2 + 2) else "middle"

    @staticmethod
    def _classify_button(text, color, x, y):
        normalized = text.lower().replace(" ", "")
        ratios = {"1/3": 1 / 3, "1/2": .5, "2/3": 2 / 3, "1.2": 1.2}
        for label, value in ratios.items():
            if label in normalized:
                return "quick_bet", value
        if re.fullmatch(r"1(?:\.0)?", normalized):
            return "quick_bet", 1.0
        if "自由" in normalized or "加注" in normalized:
            return "custom_raise", None
        if "all" in normalized:
            return "call", "allin"
        number = re.search(r"\d+(?:\.\d+)?", normalized)
        if color == "blue" and x > .58 and y > .70 and number:
            return "call", float(number.group())
        if color == "red" and x <= .48 and y >= .72:
            return "fold", None
        check_text = any(word in normalized for word in ("让牌", "过牌", "check"))
        if color in ("green", "gray") and x > .58 and y > .70 and check_text:
            return "check", None
        if check_text:
            return "check", None
        return None, None

    @staticmethod
    def _deduplicate_buttons(buttons):
        result = []
        for button in sorted(buttons, key=lambda item: item.get("confidence", .5), reverse=True):
            if any(abs(button.get("x", -1) - other.get("x", -2)) < .045 and
                   abs(button.get("y", -1) - other.get("y", -2)) < .045
                   for other in result):
                continue
            result.append(button)
        return sorted(result, key=lambda item: item.get("x", 0))

    def _update_action_log(self, seats, layout):
        for seat in seats:
            key = seat["index"]
            action = seat.get("action", "waiting")
            previous = self.previous_actions.get(key)
            if action not in ("waiting", previous):
                self.action_log.append({"time": time.time(), "seat": key + 1, "name": seat.get("name", ""), "action": action, "amount": seat.get("streetBet", 0)})
            self.previous_actions[key] = action
        return self.action_log[-30:]

    @staticmethod
    def _unacted_count(seats):
        return sum(1 for seat in seats if seat.get("occupancy") == "occupied" and seat.get("action") == "waiting" and seat.get("chips") is not None)

    def _read_seat(self, frame, index, center, table_ocr):
        height, width = frame.shape[:2]
        cx, cy = int(width * center[0]), int(height * center[1])
        avatar_center = self._nearest_avatar(frame, (cx, cy))
        ax, ay, radius = avatar_center
        name_box = self._seat_slot_box(index, "name", width, height)
        avatar_box = self._seat_slot_box(index, "avatar", width, height)
        chips_box = self._seat_slot_box(index, "chips", width, height)
        if chips_box:
            x1, y1, x2, y2 = chips_box
            y1 = y1 + round((y2 - y1) * .42)
            chips_box = (x1, y1, x2, y2)
        name_items = self._items_in_box(table_ocr, *name_box) if name_box else []
        avatar_items = self._items_in_box(table_ocr, *avatar_box) if avatar_box else []
        chips_items = self._items_in_box(table_ocr, *chips_box) if chips_box else []
        action_items = []
        name_text = " ".join(item["text"] for item in name_items)
        chips_text = " ".join(item["text"] for item in chips_items)
        action_text = " ".join(item["text"] for item in action_items)
        name = self._extract_name(name_text)
        chips = self._extract_number(chips_text)
        chip_confidence = max((float(item["confidence"]) for item in chips_items
                               if self._extract_number(item["text"]) is not None), default=0.0)
        chip_confidence = self._chip_confidence_with_consensus(
            index, chips, chips_text, chip_confidence)
        action = next((action for action, words in ACTION_WORDS.items() if any(word.lower() in action_text.lower() for word in words)), "waiting")
        confidence_items = name_items + chips_items + action_items
        confidence = sum(item["confidence"] for item in confidence_items) / len(confidence_items) if confidence_items else 0.0
        avatar_crop = self._crop_avatar(frame, avatar_center)
        avatar_text = "".join(item["text"] for item in avatar_items)
        inner_avatar = cv2.resize(avatar_crop, (64, 64))[12:52, 12:52] if avatar_crop.size else np.empty((0, 0, 3), dtype=np.uint8)
        saturation = float(cv2.cvtColor(inner_avatar, cv2.COLOR_BGR2HSV)[:, :, 1].mean()) if inner_avatar.size else 0
        countdown = bool(re.search(r"\b\d{1,2}s\b", avatar_text, re.I))
        empty = "空" in avatar_text
        if countdown or "等待" in avatar_text or "暂离" in avatar_text:
            action = "waiting"
        elif "弃牌" in avatar_text:
            action = "fold"
        avatar_reliable = bool(not empty and action != "fold" and "弃牌" not in avatar_text and saturation >= 25)
        avatar, avatar_hash = self._avatar_data(avatar_crop) if avatar_reliable else ("", "")
        proposed = {"name": "" if empty else name, "chips": None if empty else chips, "action": "empty" if empty else action, "empty": empty}
        stable = self._double_frame(index, proposed, .90 if empty else confidence)
        chip_confidence = self._stable_chip_confidence(
            index, stable.get("chips"), chips, chip_confidence)
        bet = None if stable.get("empty") else self._extract_bet(action_text)
        if bet in (None, 0):
            numeric = [(self._extract_number(item["text"]), item["cx"], item["cy"]) for item in action_items]
            if ay < height * .22:
                numeric = [value for value, item_x, item_y in numeric if value is not None]
            else:
                numeric = [value for value, item_x, item_y in numeric if value is not None
                           and abs(item_y - ay) <= radius * 1.15
                           and (item_x - ax if ax < width * .42 else ax - item_x if ax > width * .58 else abs(item_x - ax)) >= radius * .7]
            bet = min(numeric) if numeric else None
        avatar_present = bool(avatar_reliable and (name or chips is not None))
        seat_present = bool(not empty and (name or chips is not None or "弃牌" in avatar_text))
        return {"index": index, "name": stable.get("name", ""), "chips": stable.get("chips"),
                "chipConfidence": chip_confidence, "streetBet": bet,
                "action": stable.get("action", "waiting"), "empty": bool(stable.get("empty")),
                "seatPresent": seat_present, "avatarPresent": avatar_present,
                "avatarReliable": avatar_reliable, "avatar": avatar, "avatarHash": avatar_hash,
                "confidence": confidence, "position": ""}

    def _chip_confidence_with_consensus(self, index, value, text, confidence):
        explicit_money = isinstance(value, (int, float)) and "." in str(text)
        if not explicit_money or confidence < .55:
            self.chip_observations.pop(index, None)
            return confidence
        previous = self.chip_observations.get(index)
        if previous and abs(float(previous["value"]) - float(value)) <= .001:
            observation = {"value": value, "count": previous["count"] + 1,
                           "minimumConfidence": min(previous["minimumConfidence"], confidence)}
        else:
            observation = {"value": value, "count": 1, "minimumConfidence": confidence}
        self.chip_observations[index] = observation
        if observation["count"] >= 2 and observation["minimumConfidence"] >= .75:
            return max(.9, confidence)
        return confidence

    def _stable_chip_confidence(self, index, stable_value, observed_value, observed_confidence):
        previous = self.stable_chip_confidences.get(index)
        if (isinstance(stable_value, (int, float)) and isinstance(observed_value, (int, float)) and
                abs(float(stable_value) - float(observed_value)) <= .001):
            confidence = max(float(observed_confidence or 0),
                             float(previous.get("confidence") or 0)
                             if previous and abs(float(previous["value"]) - float(stable_value)) <= .001 else 0)
            self.stable_chip_confidences[index] = {"value": stable_value, "confidence": confidence}
            return confidence
        if (isinstance(stable_value, (int, float)) and previous and
                abs(float(previous["value"]) - float(stable_value)) <= .001):
            return float(previous["confidence"])
        return 0.0

    def _hero_avatar_match(self, frame, hero_index):
        try:
            reference = cv2.imdecode(np.fromfile(HERO_AVATAR_FILE, dtype=np.uint8), cv2.IMREAD_COLOR)
        except OSError:
            reference = None
        if reference is None:
            return False
        height, width = frame.shape[:2]
        center = TABLE_LAYOUTS[self.layout][hero_index]
        avatar = self._crop_avatar(frame, self._nearest_avatar(frame, (int(width * center[0]), int(height * center[1]))))
        if avatar.size == 0:
            return False
        avatar = cv2.resize(avatar, (64, 64)); reference = cv2.resize(reference, (64, 64))
        avatar_hist = cv2.calcHist([avatar], [0, 1], None, [16, 16], [0, 256, 0, 256])
        reference_hist = cv2.calcHist([reference], [0, 1], None, [16, 16], [0, 256, 0, 256])
        cv2.normalize(avatar_hist, avatar_hist); cv2.normalize(reference_hist, reference_hist)
        color_score = cv2.compareHist(avatar_hist, reference_hist, cv2.HISTCMP_CORREL)
        avatar_gray = cv2.cvtColor(avatar, cv2.COLOR_BGR2GRAY).astype(float)
        reference_gray = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY).astype(float)
        structure_score = np.corrcoef(avatar_gray.flatten(), reference_gray.flatten())[0, 1]
        score = .65 * color_score + .35 * max(0, structure_score if np.isfinite(structure_score) else 0)
        return bool(score >= .55)

    @staticmethod
    def _items_in_box(items, x1, y1, x2, y2):
        return [item for item in items if x1 <= item["cx"] <= x2 and y1 <= item["cy"] <= y2]

    def _detect_layout(self, frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        circles = cv2.HoughCircles(gray, cv2.HOUGH_GRADIENT, 1.2, int(frame.shape[1] * .07), param1=100, param2=35, minRadius=int(frame.shape[1] * .035), maxRadius=int(frame.shape[1] * .10))
        points = [] if circles is None else [(x / frame.shape[1], y / frame.shape[0]) for x, y, _ in circles[0]]
        score = {}
        for name, centers in TABLE_LAYOUTS.items():
            score[name] = sum(1 for cx, cy in centers if any((x - cx) ** 2 + (y - cy) ** 2 < .075 ** 2 for x, y in points))
        if score["8max"] >= score["6max"] - 1:
            return "8max"
        return "6max"

    @staticmethod
    def _nearest_avatar(frame, expected):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        radius = int(frame.shape[1] * .065)
        x, y = expected
        margin = int(frame.shape[1] * .10)
        x1, y1, x2, y2 = max(0, x - margin), max(0, y - margin), min(frame.shape[1], x + margin), min(frame.shape[0], y + margin)
        local = gray[y1:y2, x1:x2]
        circles = cv2.HoughCircles(local, cv2.HOUGH_GRADIENT, 1.2, max(20, radius), param1=100, param2=28, minRadius=int(radius * .65), maxRadius=int(radius * 1.35))
        if circles is None:
            return x, y, radius
        best = min(circles[0], key=lambda circle: (x1 + circle[0] - x) ** 2 + (y1 + circle[1] - y) ** 2)
        return round(x1 + best[0]), round(y1 + best[1]), round(best[2])

    @staticmethod
    def _crop_avatar(frame, avatar):
        x, y, radius = avatar
        radius = max(12, int(radius * 1.04))
        x1, y1, x2, y2 = max(0, x - radius), max(0, y - radius), min(frame.shape[1], x + radius), min(frame.shape[0], y + radius)
        crop = frame[y1:y2, x1:x2]
        size = min(crop.shape[:2])
        return crop[:size, :size]

    def _double_frame(self, index, value, confidence):
        if confidence < .55:
            return self.stable.get(index, {})
        signature = json.dumps(value, ensure_ascii=False, sort_keys=True)
        previous = self.pending.get(index)
        if previous and previous["signature"] == signature:
            self.stable[index] = value
        self.pending[index] = {"signature": signature, "time": time.time()}
        return self.stable.get(index, {})

    def _ocr(self, image):
        if image.size == 0:
            return "", 0.0
        with self.ocr_lock:
            result, _ = self.ocr(image)
        if not result:
            return "", 0.0
        text = " ".join(item[1] for item in result)
        confidence = sum(float(item[2]) for item in result) / len(result)
        return text, confidence

    def _ocr_line(self, image):
        if image.size == 0:
            return "", 0.0
        with self.ocr_lock:
            result, _ = self.ocr(image, use_det=False, use_cls=False, use_rec=True)
        if not result:
            return "", 0.0
        if isinstance(result, (list, tuple)) and len(result) >= 2 and isinstance(result[0], str):
            return result[0], float(result[1])
        item = result[0] if isinstance(result, list) else result
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            return str(item[-2]), float(item[-1])
        return "", 0.0

    def _button_ocr_line(self, image):
        if image.size == 0:
            return "", 0.0
        signature = hashlib.blake2s(image.tobytes(), digest_size=8).hexdigest()
        cached = self.button_ocr_cache.get(signature)
        if cached is not None:
            return cached
        result, _ = self.button_ocr(image, use_det=False, use_cls=False, use_rec=True)
        if isinstance(result, (list, tuple)) and len(result) >= 2 and isinstance(result[0], str):
            recognized = (result[0], float(result[1]))
        else:
            item = result[0] if isinstance(result, list) and result else result
            recognized = ((str(item[-2]), float(item[-1]))
                          if isinstance(item, (list, tuple)) and len(item) >= 2 else ("", 0.0))
        self.button_ocr_cache[signature] = recognized
        while len(self.button_ocr_cache) > 64:
            self.button_ocr_cache.pop(next(iter(self.button_ocr_cache)))
        return recognized

    def _decision_chip_ocr_line(self, image):
        if image.size == 0:
            return "", 0.0
        with self.decision_chip_ocr_lock:
            result, _ = self.decision_chip_ocr(
                image, use_det=False, use_cls=False, use_rec=True)
        if isinstance(result, (list, tuple)) and len(result) >= 2 and isinstance(result[0], str):
            return result[0], float(result[1])
        item = result[0] if isinstance(result, list) and result else result
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            return str(item[-2]), float(item[-1])
        return "", 0.0

    def _recognize_button_frame_pot_line(self, frame):
        value, confidence, _ = self._recognize_button_frame_pot_evidence(frame)
        return value, confidence

    def _recognize_button_frame_pot_evidence(self, frame):
        height, width = frame.shape[:2]
        crop = frame[int(height * .240):int(height * .276),
                     int(width * .34):int(width * .66)]
        if crop.size == 0:
            return None, 0.0, ""
        text, confidence = self._button_ocr_line(cv2.resize(
            crop, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC))
        return self._extract_number(text), float(confidence or 0), str(text)

    def _validated_button_frame_pot_line(self, frame, frame_sequence):
        pot, confidence, text = self._recognize_button_frame_pot_evidence(frame)
        field = self.fields.snapshot().get("pot", {})
        previous = field.get("value") if not field.get("stale", True) else None
        if not isinstance(previous, (int, float)):
            previous = self.hand_state.get("pot")
        explicit_decimal = confidence >= .85 and "." in text and bool(re.search(r"\d", text))
        if (explicit_decimal and isinstance(pot, (int, float)) and
                isinstance(previous, (int, float)) and any(
                    abs(float(previous) - float(pot) * ratio) <= max(.01, abs(float(previous)) * .002)
                    for ratio in (10, 100, 1000))):
            self.center_pot_candidate = None
            return pot, confidence
        if isinstance(pot, (int, float)) and isinstance(previous, (int, float)):
            tolerance = max(.01, abs(float(previous)) * .002)
            if any(abs(float(pot) - float(previous) * ratio) <= tolerance * ratio
                   for ratio in (10, 100, 1000)):
                return None, 0.0
        result = self._validate_center_pot_result({
            "pot": pot, "confidence": confidence,
            "runtimeId": self.runtime_id, "tableSession": self.table_session,
            "handId": self.hand_state.get("id"), "street": self.hand_state.get("street"),
            "frameSequence": frame_sequence,
        })
        return result.get("pot"), float(result.get("confidence") or 0)

    def _ocr_items(self, image, wait=True):
        if image.size == 0:
            return []
        if not self.ocr_lock.acquire(blocking=wait):
            return []
        scale = min(1.0, 900 / max(image.shape[:2]))
        sample = cv2.resize(image, None, fx=scale, fy=scale) if scale < 1 else image
        try:
            result, _ = self.ocr(sample)
        finally:
            self.ocr_lock.release()
        if not result:
            return []
        items = []
        for item in result:
            if isinstance(item, dict):
                text = item.get("text", "")
                confidence = item.get("confidence", item.get("score", 0.0))
                box = item.get("box", item.get("points"))
            elif isinstance(item, (list, tuple)) and len(item) >= 3:
                box, text, confidence = item[0], item[1], item[2]
            elif isinstance(item, (list, tuple)) and len(item) == 2 and isinstance(item[0], str):
                box, text, confidence = None, item[0], item[1]
            else:
                continue
            try:
                confidence = float(confidence)
            except (TypeError, ValueError):
                continue
            if box is None:
                cx = cy = 0.0
                x1 = x2 = y1 = y2 = None
            else:
                try:
                    points = np.array(box, dtype=float) / scale
                    cx = float(points[:, 0].mean())
                    cy = float(points[:, 1].mean())
                    x1, y1 = float(points[:, 0].min()), float(points[:, 1].min())
                    x2, y2 = float(points[:, 0].max()), float(points[:, 1].max())
                except (TypeError, ValueError, IndexError):
                    cx = cy = 0.0
                    x1 = x2 = y1 = y2 = None
            items.append({"text": str(text), "confidence": confidence,
                          "cx": cx, "cy": cy, "x1": x1, "x2": x2,
                          "y1": y1, "y2": y2})
        return items

    @staticmethod
    def _extract_number(text):
        normalized = re.sub(r"(?i)(?<=[\$¥￥])o(?=[\.,]\d)", "0", text or "")
        values = re.findall(r"\d+(?:\.\d+)?", normalized)
        return float(values[-1]) if values else None

    @staticmethod
    def _extract_call(text):
        match = re.search(r"(?:跟注|call)\s*(\d+(?:\.\d+)?)", text or "", re.I)
        return float(match.group(1)) if match else None

    @staticmethod
    def _extract_bet(text):
        match = re.search(r"(?:加注|下注|跟注|raise|bet|call)\s*(\d+(?:\.\d+)?)", text or "", re.I)
        return float(match.group(1)) if match else 0.0

    @staticmethod
    def _extract_investment_amount(text):
        normalized = (text or "").replace(" ", "")
        currency_index = normalized.find("$")
        if currency_index >= 0 and re.match(r"[A-Za-z]+(?:\.)?\d", normalized[currency_index + 1:]):
            return None
        values = re.findall(r"[$¥￥]?([0-9]+(?:\.[0-9]+)?|\.[0-9]+)", normalized)
        if not values:
            return None
        value = values[-1]
        if value.startswith("."):
            value = f"0{value}"
        if "." not in value and len(value) == 3 and value.startswith("0"):
            value = f"0.{value[1:]}"
        return float(value)

    @staticmethod
    def _extract_name(text):
        parts = [item for item in re.split(r"\s+", text or "") if item and not re.fullmatch(r"[+\-]\d+(?:\.\d+)?", item)]
        parts = [item for item in parts if not any(word in item.lower() for words in ACTION_WORDS.values() for word in words)]
        normal = [item for item in parts if item.rstrip(".．…").lower() not in ("mvp", "jp") and "�" not in item]
        normalized = []
        for item in normal:
            match = re.fullmatch(r"([A-Za-z\u4e00-\u9fff0-9_]{2,24})(?:[.．…]{1,3})?", item)
            if match:
                normalized.append((match.group(1)[:21] + "...") if match.group(0) != match.group(1)
                                  else match.group(1)[:24])
        normal = normalized
        if normal:
            return normal[0][:24]
        return "MVP" if any("mvp" in item.lower() for item in parts) else ""

    @staticmethod
    def _avatar_data(image):
        if image.size == 0:
            return "", ""
        resized = cv2.resize(image, (64, 64))
        gray = cv2.cvtColor(resized[8:56, 8:56], cv2.COLOR_BGR2GRAY)
        small = cv2.resize(gray, (8, 8), interpolation=cv2.INTER_AREA)
        bits = "".join("1" if value > small.mean() else "0" for value in small.flatten())
        digest = f"ah1:{int(bits, 2):016x}"
        ok, encoded = cv2.imencode(".jpg", resized, [cv2.IMWRITE_JPEG_QUALITY, 75])
        data = base64.b64encode(encoded).decode() if ok else ""
        return f"data:image/jpeg;base64,{data}" if data else "", digest

    @staticmethod
    def _avatar_hash_distance(first, second):
        if first == second:
            return 0
        if not (str(first).startswith("ah1:") and str(second).startswith("ah1:")):
            return 65
        try:
            return (int(str(first)[4:], 16) ^ int(str(second)[4:], 16)).bit_count()
        except ValueError:
            return 65

    def _recognize_cards(self, image):
        if image.size == 0:
            return []
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        mask = cv2.inRange(gray, 150, 255)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        rectangles = []
        for contour in contours:
            x, y, width, height = cv2.boundingRect(contour)
            ratio = width / max(height, 1)
            if height >= image.shape[0] * .22 and .48 <= ratio <= .82:
                parsed = self._read_card(image[y:y + height, x:x + width])
                if parsed:
                    rectangles.append((x, parsed))
        if 3 <= len(rectangles) <= 5:
            return [card for _, card in sorted(rectangles)][:5]
        merged = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (9, 15)))
        merged_contours, _ = cv2.findContours(merged, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        bands = []
        for contour in merged_contours:
            x, y, width, height = cv2.boundingRect(contour)
            if width >= height * 2.5 and height >= image.shape[0] * .06:
                bands.append((width * height, x, y, width, height))
        if bands:
            _, x, y, width, height = max(bands)
            count = min(5, max(3, round(width / max(height * .7, 1))))
            cards = []
            for index in range(count):
                left = x + round(width * index / count)
                right = x + round(width * (index + 1) / count)
                parsed = self._read_card(image[y:y + height, left:right])
                if parsed:
                    cards.append(parsed)
            if len(cards) >= 3:
                return cards[:5]
        candidates = []
        for contour in contours:
            x, y, width, height = cv2.boundingRect(contour)
            ratio = width / max(height, 1)
            if height < image.shape[0] * .10 or not .42 <= ratio <= .90:
                continue
            parsed = self._read_card(image[y:y + height, x:x + width])
            if parsed:
                candidates.append((x, parsed))
        return [card for _, card in sorted(candidates)][:5]

    def _recognize_cards_fast(self, image):
        if image.size == 0 or not self.card_rank_templates:
            return []
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        mask = cv2.inRange(gray, 150, 255)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        boxes = []
        for contour in contours:
            x, y, width, height = cv2.boundingRect(contour)
            ratio = width / max(height, 1)
            if height >= image.shape[0] * .22 and .48 <= ratio <= .82:
                boxes.append((x, y, width, height))
        result = []
        for x, y, width, height in sorted(boxes):
            card = image[y:y + height, x:x + width]
            rank = self._match_rank_template(card)
            suit = self._card_suit(card)
            if rank and suit:
                result.append(rank + suit)
        return result[:5]

    def _recognize_board_card_slots(self, frame, broad_region=None):
        height, width = frame.shape[:2]
        reference_boxes = (
            (185, 885, 300, 1060), (285, 885, 400, 1060),
            (385, 885, 500, 1060), (485, 885, 600, 1060),
            (585, 885, 700, 1060),
        )
        visible_count = self._count_card_boxes(broad_region) if broad_region is not None else 0
        if visible_count not in (3, 4, 5):
            return []
        published = list(self.card_published.get("boardCards", []))
        detected_cards = self._board_card_crops(broad_region)
        if len(detected_cards) == visible_count:
            detected = []
            for index, crop in enumerate(detected_cards):
                recognized = self._recognize_cards_fast(crop)
                card = recognized[0] if len(recognized) == 1 else None
                if card is None and index < len(published):
                    card = published[index]
                if card is None:
                    break
                detected.append(card)
            if len(detected) == visible_count and len(set(detected)) == len(detected):
                return detected
        cards = []
        for index, reference_box in enumerate(reference_boxes[:visible_count]):
            x1, y1, x2, y2 = self._reviewed_slot_box(reference_box, width, height)
            recognized = self._recognize_cards_fast(frame[y1:y2, x1:x2])
            card = recognized[0] if len(recognized) == 1 else None
            if card is None and index < len(published):
                card = published[index]
            if card is None:
                return []
            cards.append(card)
        return cards if len(set(cards)) == len(cards) else []

    @staticmethod
    def _board_card_crops(image):
        if image is None or image.size == 0:
            return []
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        mask = cv2.inRange(gray, 150, 255)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        boxes = []
        for contour in contours:
            x, y, width, height = cv2.boundingRect(contour)
            ratio = width / max(height, 1)
            if height >= image.shape[0] * .22 and .48 <= ratio <= .82:
                boxes.append((x, y, width, height))
        boxes.sort()
        return [image[y:y + height, x:x + width]
                for x, y, width, height in boxes[:5]]

    @staticmethod
    def _count_card_boxes(image):
        return RecognitionLayer.count_card_boxes(image)

    @staticmethod
    def _hero_gray_cards_visible(image):
        if image.size == 0:
            return False
        height, width = image.shape[:2]
        patches = [
            image[int(height * .44):int(height * .63), int(width * .29):int(width * .50)],
            image[int(height * .44):int(height * .63), int(width * .50):int(width * .71)],
        ]
        for patch in patches:
            if patch.size == 0:
                return False
            gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
            hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
            edge_ratio = np.count_nonzero(cv2.Canny(gray, 25, 70)) / max(gray.size, 1)
            if edge_ratio < .05 or float(hsv[:, :, 1].mean()) > 100 or not 35 <= float(hsv[:, :, 2].mean()) <= 100:
                return False
        return True

    def _match_rank_template(self, card):
        distances = RecognitionLayer.rank_distances(card, self.card_rank_templates)
        if not distances:
            return None
        distances.sort()
        distance, rank = distances[0]
        competing = next((item for item in distances[1:] if item[1] != rank), None)
        if (competing and {rank, competing[1]} == {"2", "7"} and
                competing[0] - distance < 2.0):
            diagnostic = {"appVersion": APP_VERSION, "recordedAt": time.time(),
                          "best": rank, "second": competing[1],
                          "bestDistance": round(distance, 3),
                          "secondDistance": round(competing[0], 3),
                          "gap": round(competing[0] - distance, 3),
                          "field": getattr(self, "_card_recognition_field", "unknown"),
                          "handId": self.hand_state.get("id", 0),
                          "handKey": getattr(self, "history_store", None) and
                                     f"{self.history_store.session_id}-{self.hand_state.get('id', 0)}"}
            signature = (diagnostic["field"], diagnostic["best"], diagnostic["second"])
            now = diagnostic["recordedAt"]
            if now - self.card_diagnostic_last.get(signature, 0) >= .25:
                self.card_diagnostic_last[signature] = now
                try:
                    self._append_bounded_audit(self.card_diagnostic_file, diagnostic)
                except OSError:
                    pass
            self.fields.commit("cardRankAmbiguity", {"best": rank, "second": competing[1],
                               "bestDistance": round(distance, 2), "gap": round(competing[0] - distance, 2)},
                               .35, "cards", False)
            return None
        return rank if distance <= 45 else None

    @staticmethod
    def _card_suit(card):
        return RecognitionLayer.card_suit(card)

    def _recognize_hero_cards(self, frame, ocr_items):
        height, width = frame.shape[:2]
        region = frame[int(height * .72):int(height * .97), int(width * .25):int(width * .75)]
        cards = self._recognize_cards(region)[:2]
        hero_rank_items = [item for item in ocr_items
                           if width * .34 <= item["cx"] <= width * .66 and
                           height * .79 <= item["cy"] <= height * .90 and
                           re.fullmatch(r"10|[2-9AJQK]", item["text"].strip().upper())]
        self.hero_cards_present = len(cards) == 2 or len(hero_rank_items) == 2
        if len(cards) == 2:
            hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
            white_ratio = np.count_nonzero((hsv[:, :, 2] > 170) & (hsv[:, :, 1] < 85)) / max(hsv.shape[0] * hsv.shape[1], 1)
            if white_ratio >= .035:
                self.locked_hero_cards = list(cards)
                self.locked_hero_hand_id = self.hand_state.get("id", 0)
                return cards
            if self.locked_hero_cards and self.locked_hero_hand_id == self.hand_state.get("id", 0):
                recognized_ranks = [card[0] for card in cards]
                locked_ranks = [card[0] for card in self.locked_hero_cards]
                if recognized_ranks == locked_ranks:
                    return list(self.locked_hero_cards)
            return []
        rank_items = hero_rank_items
        if len(rank_items) != 2:
            return []
        result = []
        for item in sorted(rank_items, key=lambda value: value["cx"]):
            rank = "T" if item["text"].strip() == "10" else item["text"].strip().upper()
            cx, cy = int(item["cx"]), int(item["cy"])
            suit_region = frame[cy + 5:min(height, cy + 55), max(0, cx - 10):min(width, cx + 20)]
            hsv = cv2.cvtColor(suit_region, cv2.COLOR_BGR2HSV)
            hue = hsv[:, :, 0][hsv[:, :, 1] > 75]
            if not hue.size:
                suit = "s"
            elif np.count_nonzero((hue >= 35) & (hue <= 90)) >= hue.size * .35:
                suit = "c"
            elif np.count_nonzero((hue <= 12) | (hue >= 165)) >= hue.size * .20:
                suit = "d"
            else:
                suit = "s"
            result.append(rank + suit)
        hsv_region = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
        white_ratio = np.count_nonzero((hsv_region[:, :, 2] > 170) & (hsv_region[:, :, 1] < 85)) / max(hsv_region.shape[0] * hsv_region.shape[1], 1)
        if white_ratio < .035:
            if self.locked_hero_cards and self.locked_hero_hand_id == self.hand_state.get("id", 0):
                return list(self.locked_hero_cards)
            return []
        self.locked_hero_cards = list(result)
        self.locked_hero_hand_id = self.hand_state.get("id", 0)
        return result

    def _recognize_hero_name(self, frame):
        height, width = frame.shape[:2]
        crop = frame[int(height * .675):int(height * .755), int(width * .30):int(width * .70)]
        if crop.size == 0:
            return ""
        enlarged = cv2.resize(crop, None, fx=2.5, fy=2.5, interpolation=cv2.INTER_CUBIC)
        text, _ = self._ocr(enlarged)
        return text

    def _read_card(self, card):
        height, width = card.shape[:2]
        rank_crop = card[:max(1, int(height * .70)), :width]
        rank_crop = cv2.resize(rank_crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
        rank_text, rank_confidence = self._ocr(rank_crop)
        rank_match = re.search(r"10|[2-9AJQKT]", rank_text.upper())
        glyph = cv2.cvtColor(card[:max(1, int(height * .55)), :max(1, int(width * .55))], cv2.COLOR_BGR2GRAY)
        glyph = cv2.resize(glyph, (20, 32)).flatten().astype(float)
        if not rank_match or rank_confidence < .50:
            correlations = {}
            for candidate, values in self.card_templates.items():
                template = np.array(values, dtype=float)
                if template.size == glyph.size:
                    correlation = np.corrcoef(glyph, template)[0, 1]
                    if np.isfinite(correlation):
                        correlations[candidate] = correlation
            if not correlations:
                return None
            rank = max(correlations, key=correlations.get)
            if correlations[rank] <= .62:
                return None
        else:
            rank = "T" if rank_match.group() == "10" else rank_match.group()
        if rank in ("6", "9") and self.card_templates.get("9") and self.card_templates.get("6"):
            correlations = {candidate: np.corrcoef(glyph, np.array(self.card_templates[candidate], dtype=float))[0, 1] for candidate in ("6", "9")}
            rank = max(correlations, key=correlations.get)
        inner = card[int(height * .42):max(int(height * .43) + 1, int(height * .92)), int(width * .15):max(int(width * .16) + 1, int(width * .85))]
        hsv = cv2.cvtColor(inner, cv2.COLOR_BGR2HSV)
        saturated = hsv[:, :, 1] > 80
        hue = hsv[:, :, 0][saturated]
        saturation_ratio = float(np.count_nonzero(saturated)) / saturated.size
        if not hue.size or saturation_ratio < .025:
            suit = "s"
        else:
            green = np.count_nonzero((hue >= 35) & (hue <= 90))
            blue = np.count_nonzero((hue > 90) & (hue <= 135))
            red = np.count_nonzero((hue < 12) | (hue > 165))
            dominant = max(green, blue, red) / saturated.size
            suit = "s" if dominant < .08 else "c" if green == max(green, blue, red) else "d" if blue == max(green, blue, red) else "h"
        return f"{rank}{suit}"

    @staticmethod
    def _load_config():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"bbox": DEFAULT_BBOX}

    @staticmethod
    def _load_rank_templates():
        try:
            return json.loads(RANK_TEMPLATE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _auto_calibrate(self):
        detected = self._detect_green_projection(ImageGrab.grab(all_screens=True))
        if detected:
            windows = visible_windows()
            recording_window = recording_window_for_region(windows, detected)
            if recording_window:
                recording_bbox = self._recording_content_bbox(recording_window)
                if recording_bbox:
                    return self._save_bbox(recording_bbox, f"自动跟随录像内容区域 {recording_window['title']}", recording_window["hwnd"])
            projection_window = projection_window_for_region(windows, detected)
            if projection_window:
                return self._save_bbox(projection_window["bbox"], f"自动跟随完整投屏窗口 {projection_window['title'] or '竖屏窗口'}", projection_window["hwnd"])
            return self._save_bbox(detected, "自动检测绿色牌桌外沿")
        windows = visible_windows()
        keywords = ("5kplayer", "wepoker", "airplay", "投屏", "镜像")
        candidates = [window for window in windows if any(word in window["title"].lower() for word in keywords)]
        if candidates:
            window = max(candidates, key=lambda item: (item["bbox"][2] - item["bbox"][0]) * (item["bbox"][3] - item["bbox"][1]))
            return self._save_bbox(window["bbox"], f"自动跟随 {window['title'] or '竖屏窗口'}", window["hwnd"])
        return None

    def _recording_content_bbox(self, window):
        bbox = list(map(int, window["bbox"]))
        cache_key = (window.get("hwnd"), *bbox)
        if getattr(self, "_recording_content_cache_key", None) == cache_key:
            return list(self._recording_content_cache_bbox)
        try:
            screenshot = ImageGrab.grab(bbox=tuple(bbox), all_screens=True)
            detected = self._detect_green_projection(screenshot)
        except OSError:
            return None
        if not detected:
            return None
        left, top = bbox[:2]
        result = [left + detected[0], top + detected[1],
                  left + detected[2], top + detected[3]]
        self._recording_content_cache_key = cache_key
        self._recording_content_cache_bbox = result
        return list(result)

    def _save_bbox(self, bbox, source, hwnd=None):
        self.config.update({"bbox": [int(value) for value in bbox], "hwnd": hwnd, "source": source})
        if hwnd:
            window = next((item for item in visible_windows() if item["hwnd"] == hwnd), None)
            if window:
                wx1, wy1, wx2, wy2 = window["bbox"]
                width, height = max(wx2 - wx1, 1), max(wy2 - wy1, 1)
                x1, y1, x2, y2 = bbox
                self.config["relative"] = [(x1 - wx1) / width, (y1 - wy1) / height, (x2 - wx1) / width, (y2 - wy1) / height]
        CONFIG_FILE.write_text(json.dumps(self.config, ensure_ascii=False, indent=2), encoding="utf-8")
        x1, y1, x2, y2 = self.config["bbox"]
        return {"status": f"{source}：{x1},{y1}–{x2},{y2}", "bbox": self.config["bbox"]}

    def _current_bbox(self):
        hwnd, relative = self.config.get("hwnd"), self.config.get("relative")
        if hwnd and relative and user32.IsWindow(hwnd):
            window = next((item for item in visible_windows() if item["hwnd"] == hwnd), None)
            if window:
                x1, y1, x2, y2 = window["bbox"]
                width, height = x2 - x1, y2 - y1
                return [x1 + round(relative[0] * width), y1 + round(relative[1] * height), x1 + round(relative[2] * width), y1 + round(relative[3] * height)]
        if self.tracked_bbox:
            return self.tracked_bbox
        return self.config.get("bbox", DEFAULT_BBOX)

    @staticmethod
    def _bbox_valid(bbox):
        return bool(bbox and len(bbox) == 4 and bbox[2] - bbox[0] >= 200 and bbox[3] - bbox[1] >= 400)

    @staticmethod
    def _tracking_candidate_ok(current, candidate):
        current_width, current_height = current[2] - current[0], current[3] - current[1]
        candidate_width, candidate_height = candidate[2] - candidate[0], candidate[3] - candidate[1]
        width_scale = candidate_width / max(current_width, 1)
        height_scale = candidate_height / max(current_height, 1)
        if not (.55 <= width_scale <= 1.65 and .55 <= height_scale <= 1.65):
            return False
        current_ratio = current_width / max(current_height, 1)
        candidate_ratio = candidate_width / max(candidate_height, 1)
        if abs(candidate_ratio / max(current_ratio, .01) - 1) > .18:
            return False
        current_center = ((current[0] + current[2]) / 2, (current[1] + current[3]) / 2)
        candidate_center = ((candidate[0] + candidate[2]) / 2, (candidate[1] + candidate[3]) / 2)
        reach_x = max(current_width, candidate_width) * .65
        reach_y = max(current_height, candidate_height) * .65
        return abs(current_center[0] - candidate_center[0]) <= reach_x and abs(current_center[1] - candidate_center[1]) <= reach_y

    def _overlay_bbox(self):
        x1, y1, x2, y2 = self._visible_bbox()
        return [x1 - BORDER_WIDTH, y1 - BORDER_WIDTH, x2 + BORDER_WIDTH, y2 + BORDER_WIDTH]

    @staticmethod
    def _clip_bbox_to_work_area(bbox):
        x1, y1, x2, y2 = map(int, bbox)
        monitors = []
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.wintypes.RECT), ctypes.c_ssize_t)

        class MonitorInfo(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.wintypes.DWORD), ("rcMonitor", ctypes.wintypes.RECT), ("rcWork", ctypes.wintypes.RECT), ("dwFlags", ctypes.wintypes.DWORD)]

        @callback_type
        def callback(monitor_handle, _, rect, __):
            info = MonitorInfo()
            info.cbSize = ctypes.sizeof(info)
            if user32.GetMonitorInfoW(monitor_handle, ctypes.byref(info)):
                monitors.append((info.rcWork.left, info.rcWork.top, info.rcWork.right, info.rcWork.bottom))
            return True

        user32.EnumDisplayMonitors(None, None, callback, 0)
        if not monitors:
            return [x1, y1, x2, y2]
        left, top, right, bottom = max(monitors, key=lambda item: max(0, min(x2, item[2]) - max(x1, item[0])) * max(0, min(y2, item[3]) - max(y1, item[1])))
        return [max(x1, left), max(y1, top), min(x2, right), min(y2, bottom)]

    def _find_green_near(self, bbox, margin):
        x1, y1, x2, y2 = map(int, bbox)
        left = user32.GetSystemMetrics(76)
        top = user32.GetSystemMetrics(77)
        right = left + user32.GetSystemMetrics(78)
        bottom = top + user32.GetSystemMetrics(79)
        area = [max(left, x1 - margin), max(top, y1 - margin), min(right, x2 + margin), min(bottom, y2 + margin)]
        if area[2] <= area[0] or area[3] <= area[1]:
            return None
        detected = self._detect_green_projection(ImageGrab.grab(bbox=tuple(area)))
        return [area[0] + detected[0], area[1] + detected[1], area[0] + detected[2], area[1] + detected[3]] if detected else None

    def _visible_bbox(self):
        if self.tracked_bbox:
            return list(map(int, self.tracked_bbox))
        x1, y1, x2, y2 = map(int, self._current_bbox())
        monitors = []
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.wintypes.RECT), ctypes.c_ssize_t)

        class MonitorInfo(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.wintypes.DWORD), ("rcMonitor", ctypes.wintypes.RECT), ("rcWork", ctypes.wintypes.RECT), ("dwFlags", ctypes.wintypes.DWORD)]

        @callback_type
        def callback(monitor_handle, _, rect, __):
            info = MonitorInfo()
            info.cbSize = ctypes.sizeof(info)
            if user32.GetMonitorInfoW(monitor_handle, ctypes.byref(info)):
                monitors.append((info.rcWork.left, info.rcWork.top, info.rcWork.right, info.rcWork.bottom))
            else:
                monitors.append((rect.contents.left, rect.contents.top, rect.contents.right, rect.contents.bottom))
            return True

        user32.EnumDisplayMonitors(None, None, callback, 0)
        monitor = max(monitors, key=lambda item: max(0, min(x2, item[2]) - max(x1, item[0])) * max(0, min(y2, item[3]) - max(y1, item[1]))) if monitors else (0, 0, user32.GetSystemMetrics(78), user32.GetSystemMetrics(79))
        left, top, right, bottom = monitor
        width, height = max(40, x2 - x1), max(40, y2 - y1)
        x1 = min(max(x1, left), right - 40)
        y1 = min(max(y1, top), bottom - 40)
        return [x1, y1, min(x1 + width, right), min(y1 + height, bottom)]

    @staticmethod
    def _detect_green_projection(screenshot):
        image = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        # The console also uses dark green; require the brighter, saturated felt.
        mask = cv2.inRange(hsv, np.array([35, 105, 70]), np.array([100, 255, 255]))
        row_ratio = np.count_nonzero(mask, axis=1) / max(mask.shape[1], 1)
        candidate_rows = np.flatnonzero(row_ratio >= .20)
        if candidate_rows.size:
            top, bottom = int(candidate_rows[0]), int(candidate_rows[-1])
            vertical = mask[top:bottom + 1]
            column_ratio = np.count_nonzero(vertical, axis=0) / max(vertical.shape[0], 1)
            candidate_columns = np.flatnonzero(column_ratio >= .28)
            if candidate_columns.size:
                left, right = int(candidate_columns[0]), int(candidate_columns[-1])
                width, height = right - left + 1, bottom - top + 1
                if height >= image.shape[0] * .55 and .32 <= width / max(height, 1) <= .65:
                    return [left, top, right + 1, bottom + 1]
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (31, 31)))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        options = []
        for contour in contours:
            x, y, width, height = cv2.boundingRect(contour)
            if height >= image.shape[0] * .55 and .32 <= width / max(height, 1) <= .65:
                options.append((width * height, [x, y, x + width, y + height]))
        return max(options)[1] if options else None

    @staticmethod
    def _select_region():
        screenshot = ImageGrab.grab(all_screens=True)
        virtual_left = user32.GetSystemMetrics(76)
        virtual_top = user32.GetSystemMetrics(77)
        virtual_width = user32.GetSystemMetrics(78)
        virtual_height = user32.GetSystemMetrics(79)
        preview_scale = min(1.0, 2560 / max(screenshot.size))
        preview = screenshot.resize((round(screenshot.width * preview_scale), round(screenshot.height * preview_scale)), Image.Resampling.BILINEAR) if preview_scale < 1 else screenshot
        root = tk.Tk()
        root.overrideredirect(True)
        preview_width, preview_height = preview.size
        root.geometry(f"{preview_width}x{preview_height}+{virtual_left}+{virtual_top}")
        root.attributes("-topmost", True)
        root.configure(cursor="crosshair")
        photo = tk.PhotoImage(data=base64.b64encode(_png_bytes(preview)).decode())
        canvas = tk.Canvas(root, highlightthickness=0, width=preview_width, height=preview_height)
        canvas.pack(fill="both", expand=True)
        canvas.create_image(0, 0, image=photo, anchor="nw")
        canvas.create_text(20, 20, anchor="nw", text="拖动框选完整投屏区域，Esc 取消", fill="yellow", font=("Microsoft YaHei", 18, "bold"))
        state = {"start": None, "rect": None, "bbox": None}
        def down(event):
            state["start"] = (event.x, event.y)
            state["rect"] = canvas.create_rectangle(event.x, event.y, event.x, event.y, outline="yellow", width=3)
        def move(event):
            if state["start"]:
                canvas.coords(state["rect"], *state["start"], event.x, event.y)
        def up(event):
            if state["start"]:
                x1, y1 = state["start"]
                state["bbox"] = [virtual_left + round(min(x1, event.x) / preview_scale), virtual_top + round(min(y1, event.y) / preview_scale), virtual_left + round(max(x1, event.x) / preview_scale), virtual_top + round(max(y1, event.y) / preview_scale)]
                root.after(100, root.destroy)
        canvas.bind("<ButtonPress-1>", down); canvas.bind("<B1-Motion>", move); canvas.bind("<ButtonRelease-1>", up)
        root.bind("<Escape>", lambda _: root.destroy())
        root.mainloop()
        return state["bbox"]

    @staticmethod
    def _load_templates():
        try:
            return json.loads(TEMPLATE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}


def main():
    page = APP_DIR / "wepoker-review.html"
    training_support_page = APP_DIR / "training-support.html"
    audit_page = APP_DIR / "capture-audit.html"
    hero_profile_page = APP_DIR / "hero-profile.html"
    opponent_hands_page = APP_DIR / "opponent-hands.html"
    api = Api()
    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *_):
            return
    handler = lambda *args, **kwargs: QuietHandler(*args, directory=str(APP_DIR), **kwargs)
    server = socketserver.TCPServer(("127.0.0.1", 0), handler)
    api.page_server = server
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    console_url = f"{base_url}/{page.name}?v={APP_VERSION}"
    training_support_url = f"{base_url}/{training_support_page.name}?v={APP_VERSION}"
    audit_url = f"{base_url}/{audit_page.name}?v={APP_VERSION}"
    hero_profile_url = f"{base_url}/{hero_profile_page.name}?v={APP_VERSION}"
    opponent_hands_url = f"{base_url}/{opponent_hands_page.name}?v={APP_VERSION}"
    window = webview.create_window("Poker Study Console", console_url, width=520, height=960, min_size=(420, 600))
    training_support_window = webview.create_window(
        "训练辅助面板", training_support_url, width=442, height=960,
        min_size=(360, 600))
    audit_window = webview.create_window("Capture Audit", audit_url, width=520, height=960, min_size=(420, 600))
    hero_profile_window = webview.create_window(
        "My Poker Ranges", hero_profile_url, width=1480, height=900,
        min_size=(620, 600), hidden=True)
    opponent_hands_window = webview.create_window(
        "Opponent Range Statistics", opponent_hands_url, width=1480, height=900,
        min_size=(620, 600), hidden=True)
    exposed = (
        api.capture_state,
        api.bridge_info,
        api.record_decision_latency,
        api.publish_training_decision,
        api.record_decision_audit,
        api.set_overlay,
        api.start_recognition,
        api.stop_recognition,
        api.lock_capture_box,
        api.unlock_capture_box,
        api.toggle_audit_window,
        api.hide_audit_window,
        api.set_window_docking,
        api.set_windows_topmost,
        api.solver_status,
        api.match_strategy,
        api.show_advice,
        api.audit_snapshot,
        api.audit_crops,
        api.action_audit_state,
        api.submit_audit_correction,
        api.audit_accuracy,
        api.capture_opponent_statistics,
        api.assign_opponent_statistics_seat,
        api.show_next_profile_statistics,
        api.set_strategy_mode,
        api.capture_hero_statistics,
        api.hero_profile_state,
        api.preflop_baseline_catalog,
        api.preflop_baseline_range_table,
        api.clear_hero_range_statistics,
        api.clear_hero_strategy_comparisons,
        api.set_hero_range_collection,
        api.show_hero_profile_window,
        api.hide_hero_profile_window,
        api.toggle_hero_profile_window,
        api.show_opponent_hands_window,
        api.hide_opponent_hands_window,
        api.toggle_opponent_hands_window,
        api.set_auxiliary_window_topmost,
        api.record_deep_analysis,
        api.deep_analysis_state,
    )
    window.expose(*exposed)
    training_support_window.expose(*exposed)
    audit_window.expose(*exposed)
    hero_profile_window.expose(*exposed)
    opponent_hands_window.expose(*exposed)
    api.bind_window(window, audit_window, hero_profile_window, opponent_hands_window,
                    training_support_window)
    def dock_loaded_windows():
        api.set_window_docking(True)

    def topmost_loaded_windows():
        api.set_windows_topmost(True)

    def finish_window_setup():
        time.sleep(0.25)
        dock_loaded_windows()
        topmost_loaded_windows()

    window.events.loaded += lambda: threading.Thread(target=finish_window_setup, daemon=True).start()
    audit_window.events.closing += api.on_audit_closing
    training_support_window.events.closing += api.on_training_support_closing
    hero_profile_window.events.closing += api.on_hero_profile_closing
    opponent_hands_window.events.closing += api.on_opponent_hands_closing
    window.events.closing += api.close_application
    gui = os.environ.get("POKER_WEBVIEW_GUI", "edgechromium")
    webview.start(gui=gui, debug=False, private_mode=False,
                  storage_path=str(DATA_DIR / f"webview-{APP_VERSION}"))


if __name__ == "__main__":
    main()
