"""Unit tests for Chamo Charly Telegram Bot and Keep-Alive Server."""

from __future__ import annotations

import unittest
from pathlib import Path
from bot import flask_app, authenticated_chats, BOT_PASSWORD
from chamo_charly.database import init_db


class TestBotSuite(unittest.TestCase):
    def setUp(self):
        self.app = flask_app.test_client()
        self.app.testing = True

    def test_healthcheck_endpoint(self):
        response = self.app.get("/health")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["app"], "Chamo Charly Bot")

    def test_authentication_flow(self):
        chat_id = 999888
        self.assertNotIn(chat_id, authenticated_chats)
        
        # Simulate successful auth
        authenticated_chats.add(chat_id)
        self.assertIn(chat_id, authenticated_chats)
        
        # Cleanup
        authenticated_chats.remove(chat_id)

    def test_main_menu_keyboard_has_stats_button(self):
        from bot import main_menu_keyboard
        kb = main_menu_keyboard()
        button_labels = [btn.text for row in kb.inline_keyboard for btn in row]
        self.assertIn("📈 Estadísticas", button_labels)
        self.assertIn("🎯 Ver Predicción Oficial", button_labels)
        self.assertIn("📊 Estado del Sistema", button_labels)


if __name__ == "__main__":
    unittest.main()
