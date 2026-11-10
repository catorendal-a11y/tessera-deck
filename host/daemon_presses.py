"""Running a key press: the fast lane, the slow lane for actions that wait, and double taps."""
import json
import threading
import time

BLOCKING_ACTIONS = ('shell', 'http', 'delay')  # run on the slow lane so key input stays responsive
DOUBLE_PRESS_SECONDS = 0.35  # a key with double_actions waits this long for a second tap


def action_list_name(hold, double=False):
    return 'hold_actions' if hold else 'double_actions' if double else 'actions'


class PressMixin:
    """Methods of the Daemon; they use its state."""

    def is_slow(self, button_id, hold, double=False):
        button = next((b for b in self.effective_buttons() if b['id'] == button_id), None)
        if button is None:
            return False
        actions = self.resolved_button(button).get(action_list_name(hold, double), [])
        return any(action['type'] in BLOCKING_ACTIONS or (action['type'] == 'text' and action.get('delay_ms'))
                   for action in actions)

    def start_press(self, button_id, hold=False, double=False):
        """Run a press now, or on the slow lane when it waits (shell, HTTP, delay) so other keys keep working.

        A button that is still running ignores further presses instead of running twice.
        """
        if not self.is_slow(button_id, hold, double):
            return self.dispatch_press(button_id, hold=hold, double=double)
        identity = (self.profile, self.page, button_id)
        with self.slow_lock:
            running = identity in self.slow_running
            claimed = not running and self.slow_slots.acquire(blocking=False)
            if claimed:
                self.slow_running.add(identity)
        if not claimed:
            self.log(f'Button {button_id} is still running or the slow lane is full; press ignored')
            self.panel.feedback(button_id, False)
            return False
        threading.Thread(target=self.run_slow_press, args=(button_id, hold, identity, double),
                         name=f'slow-button-{button_id}', daemon=True).start()
        return True

    def run_slow_press(self, button_id, hold, identity, double=False):
        try:
            with self.state_lock:
                self.dispatch_press(button_id, hold=hold, double=double)
        except Exception as exc:
            self.log(f'Action failed: {exc}')
        finally:
            with self.slow_lock:
                self.slow_running.discard(identity)
            self.slow_slots.release()

    def start_actions(self, actions):
        """Trigger and timer actions: a list that waits (shell, HTTP, delay) runs on the slow lane, like a slow key.

        Otherwise one slow trigger would hold up every key press behind it. A list that is still running is skipped.
        """
        if not any(action.get('type') in BLOCKING_ACTIONS for action in actions):
            for action in actions:
                self.run_action(action)
            return
        identity = ('actions', json.dumps(actions, sort_keys=True))
        with self.slow_lock:
            claimed = identity not in self.slow_running and self.slow_slots.acquire(blocking=False)
            if claimed:
                self.slow_running.add(identity)
        if not claimed:
            self.log('A trigger is still running or the slow lane is full; this run was skipped')
            return
        threading.Thread(target=self.run_slow_actions, args=(actions, identity), name='slow-actions', daemon=True).start()

    def run_slow_actions(self, actions, identity):
        try:
            with self.state_lock:
                for action in actions:
                    if self.stop.is_set():
                        break
                    self.run_action(action)
        except Exception as exc:
            self.log(f'Action failed: {exc}')
        finally:
            with self.slow_lock:
                self.slow_running.discard(identity)
            self.slow_slots.release()

    def dispatch_press(self, button_id, hold=False, double=False):
        identity = (self.profile, self.page, button_id)
        if identity in self.active_press or len(self.active_press) >= 16:
            raise ValueError('Circular button action')
        buttons = self.effective_buttons()
        button = next((b for b in buttons if b['id'] == button_id), None)
        if button is None:
            self.last_action = {'id': button_id, 'label': 'Unknown button', 'ok': False,
                                'error': 'The button does not exist on the active page', 'at': time.time()}
            self.panel.feedback(button_id, False)
            self.publish_runtime(True, force=True)
            return False
        if not self.active_press:
            self.state_set_by_action.clear()
        self.active_press.append(identity)
        state_key = self.state_key(button)
        resolved = self.resolved_button(button)
        ok, error = False, ''
        try:
            self.log(f'Button {button_id}: {button["label"]}' + (' (hold)' if hold else ' (double)' if double else ''))
            for action in resolved.get(action_list_name(hold, double), []):
                if self.stop.is_set():
                    raise RuntimeError('Stopping')
                self.run_action(action)
            if (button.get('states') and not hold and not double and not button.get('bind')
                    and state_key not in self.state_set_by_action):
                self.button_states[state_key] = (self.button_states.get(state_key, 0) + 1) % len(button['states'])
                self.push_page()
            ok = True
        except Exception as exc:
            error = str(exc)[:180]
            self.log(f'Action failed: {exc}')
        finally:
            self.active_press.pop()
            self.last_action = {'id': button_id, 'label': button['label'], 'ok': ok,
                                'error': error or None, 'at': time.time()}
            self.events.add('press', button=button_id, label=button['label'], profile=self.profile, page=self.page,
                            ok=ok, hold=hold, double=double)
            try:
                self.panel.feedback(button_id, ok)
            finally:
                self.publish_runtime(True, force=True)
        return ok

    def tap_with_double(self, button_id):
        """A tap on a key with double_actions: a second tap in time runs them, otherwise the single actions run late."""
        identity = (self.profile, self.page, button_id)
        if self.pending_single.pop(identity, None) is not None:
            self.start_press(button_id, double=True)
            return
        token = next(self.single_tokens)
        self.pending_single[identity] = token
        self.schedule_job(('single-due', identity, token), DOUBLE_PRESS_SECONDS)
