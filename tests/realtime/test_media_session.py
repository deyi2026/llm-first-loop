"""T-CONTRACT-6：连接状态机、全活动态可取消与四事实分离测试。

覆盖 RTM：SES-01/05、REC-03/05/09、LIF-01/02/04、IDN-03/07、PLY-03、CAP-14。
"""

from __future__ import annotations

import pytest

from llm_loop.realtime.media_session import (
    ConnectionState,
    MediaSession,
    NonRetryableFailure,
    PlaybackState,
    TaskState,
)


class TestReadySemantics:
    def test_ready_without_waiting_for_first_frame(self):
        session = MediaSession("m1")
        session.start()
        assert session.state is ConnectionState.OPENING
        session.mark_transport_ready()  # 握手 + 传输就绪即可
        assert session.state is ConnectionState.READY

    def test_cannot_upload_before_ready(self):
        session = MediaSession("m1")
        session.start()
        assert session.can_upload() is False  # opening 未就绪前禁止上传
        session.mark_transport_ready()
        assert session.can_upload() is True

    def test_cannot_upload_when_closed(self):
        session = MediaSession("m1")
        session.start()
        session.mark_transport_ready()
        session.close()
        assert session.can_upload() is False


class TestReconnectBounds:
    def test_retryable_error_enters_reconnecting(self):
        session = MediaSession("m1")
        session.start()
        session.mark_transport_ready()
        assert session.on_retryable_error() is ConnectionState.RECONNECTING

    def test_bounded_reconnect_then_failed(self):
        session = MediaSession("m1", max_reconnect=3)
        session.start()
        for _ in range(3):
            assert session.on_retryable_error() is ConnectionState.RECONNECTING
        assert session.on_retryable_error() is ConnectionState.FAILED  # 第 4 次：超上限

    def test_non_retryable_never_enters_reconnecting(self):
        for kind in NonRetryableFailure:
            session = MediaSession("m1")
            session.start()
            assert session.on_non_retryable_error(kind) is ConnectionState.FAILED

    def test_local_service_down_is_non_retryable(self):
        session = MediaSession("m1")
        session.start()
        assert (
            session.on_non_retryable_error(NonRetryableFailure.LOCAL_SERVICE_DOWN)
            is ConnectionState.FAILED
        )


class TestActiveStateClose:
    def test_close_from_opening(self):
        session = MediaSession("m1")
        session.start()
        assert session.close() is ConnectionState.CLOSED

    def test_close_from_ready(self):
        session = MediaSession("m1")
        session.start()
        session.mark_transport_ready()
        assert session.close() is ConnectionState.CLOSED

    def test_close_from_reconnecting(self):
        session = MediaSession("m1")
        session.start()
        session.on_retryable_error()
        assert session.state is ConnectionState.RECONNECTING
        assert session.close() is ConnectionState.CLOSED

    def test_close_disables_mic(self):
        session = MediaSession("m1")
        session.start()
        session.mark_transport_ready()
        session.set_mic(True)
        session.close()
        assert session.facts().mic_enabled is False


class TestFourFacts:
    def test_facts_are_independent_dimensions(self):
        session = MediaSession("m1")
        session.start()
        session.mark_transport_ready()
        session.set_mic(True)
        session.set_playback(PlaybackState.PLAYING)
        session.set_task(TaskState.RUNNING)
        facts = session.facts()
        assert facts.connection_state is ConnectionState.READY
        assert facts.mic_enabled is True
        assert facts.playback_state is PlaybackState.PLAYING
        assert facts.task_state is TaskState.RUNNING

    def test_facts_do_not_collapse_into_single_boolean(self):
        session = MediaSession("m1")
        session.start()
        session.mark_transport_ready()
        # 连接 ready 但麦克风关闭、播放停止、任务空闲——四事实各自独立
        facts = session.facts()
        assert facts.connection_state is ConnectionState.READY
        assert facts.mic_enabled is False
        assert facts.playback_state is PlaybackState.IDLE
        assert facts.task_state is TaskState.IDLE


class TestEpochIsolation:
    def test_stale_epoch_rejected(self):
        session = MediaSession("m1")
        session.start(epoch=5)
        with pytest.raises(ValueError):
            session.mark_transport_ready(epoch=4)  # 旧代次不得更新当前会话

    def test_new_epoch_accepted(self):
        session = MediaSession("m1")
        session.start(epoch=5)
        session.mark_transport_ready(epoch=6)
        assert session.connection_epoch == 6

    def test_restart_while_active_raises(self):
        session = MediaSession("m1")
        session.start()
        with pytest.raises(RuntimeError):
            session.start()
