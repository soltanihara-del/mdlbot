"""Persistent FSM definitions; RedisStorage owns runtime state."""

from aiogram.fsm.state import State, StatesGroup


class TelegramFileStates(StatesGroup):
    waiting_for_file = State()


class DirectUrlStates(StatesGroup):
    waiting_for_url = State()


class LanguageStates(StatesGroup):
    choosing = State()


class SupportStates(StatesGroup):
    waiting_for_subject = State()
    waiting_for_message = State()


class AdminActionStates(StatesGroup):
    waiting_for_value = State()
    waiting_for_reason = State()
    waiting_for_confirmation = State()
