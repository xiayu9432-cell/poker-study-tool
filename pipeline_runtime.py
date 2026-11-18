import os
import queue
import threading


class PipelineRuntime:
    def __init__(self, host):
        self.host = host

    def start(self):
        host = self.host
        if host.recognition_started:
            return
        host.recognition_started = True
        action_workers = max(1, min(4, int(os.environ.get("ACTION_OCR_WORKERS", "2"))))
        avatar_workers = max(1, min(4, int(os.environ.get("AVATAR_OCR_WORKERS", "2"))))
        host._action_ocr_worker_target = action_workers
        host._avatar_ocr_worker_target = avatar_workers
        host.action_ocr_ready.clear()
        host.avatar_ocr_ready.clear()
        targets = ([host._action_ocr_loop] * action_workers + [
            host._center_ocr_loop, host._fast_frame_loop, host._frame_buffer_loop,
        ] + [host._avatar_ocr_loop] * avatar_workers + [
            host._card_recognition_loop, host._peek_recognition_loop,
            host._fast_occupancy_loop, host._slow_recognition_loop,
            host._fast_recognition_loop,
        ])
        for target in targets:
            threading.Thread(target=target, daemon=True).start()

    def stop(self):
        host = self.host
        host.recognition_active.clear()
        for work_queue in (host.frame_buffer_queue, host.action_ocr_queue,
                           host.avatar_ocr_queue, host.center_ocr_queue, host.peek_queue):
            while True:
                try:
                    work_queue.get_nowait()
                    work_queue.task_done()
                except queue.Empty:
                    break
        host._discard_action_ocr_results()
