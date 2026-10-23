"""Бот @priceIAPRO_bot: подтверждает вход на сайт по контакту.

Запуск: python manage.py run_bot (на сервере — systemd-юнит price-bot).
"""
import asyncio
import logging

from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.management.base import BaseCommand

from accounts.services import confirm_login, get_pending_token

log = logging.getLogger("price.bot")

HELP_TEXT = (
    "Это бот входа на сайт price.interalex.pro.\n"
    "Откройте сайт, нажмите «Войти через Telegram» — бот попросит поделиться контактом."
)


def build_dispatcher():
    from aiogram import Dispatcher, F
    from aiogram.filters import CommandObject, CommandStart
    from aiogram.fsm.context import FSMContext
    from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove

    dp = Dispatcher()
    contact_kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Поделиться контактом", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )

    @dp.message(CommandStart(deep_link=True))
    async def start_with_code(message: Message, command: CommandObject, state: FSMContext):
        arg = command.args or ""
        if not arg.startswith("login_"):
            await message.answer(HELP_TEXT, reply_markup=ReplyKeyboardRemove())
            return
        token = arg[len("login_"):]
        if await sync_to_async(get_pending_token)(token) is None:
            await message.answer(
                "Ссылка для входа устарела. Вернитесь на сайт и нажмите «Войти» ещё раз.",
                reply_markup=ReplyKeyboardRemove(),
            )
            return
        await state.update_data(token=token)
        await message.answer("Чтобы войти на сайт, поделитесь своим контактом 👇", reply_markup=contact_kb)

    @dp.message(CommandStart())
    async def start_plain(message: Message):
        await message.answer(HELP_TEXT, reply_markup=ReplyKeyboardRemove())

    @dp.message(F.contact)
    async def got_contact(message: Message, state: FSMContext):
        token = (await state.get_data()).get("token")
        if not token:
            await message.answer(HELP_TEXT, reply_markup=ReplyKeyboardRemove())
            return
        user = message.from_user
        ok, text = await sync_to_async(confirm_login)(
            token=token,
            telegram_id=user.id,
            contact_user_id=message.contact.user_id or 0,
            phone=message.contact.phone_number,
            username=user.username or "",
            full_name=user.full_name or "",
        )
        await state.clear()
        log.info("login %s: tg=%s ok=%s", token[:6], user.id, ok)
        await message.answer(text, reply_markup=ReplyKeyboardRemove())

    @dp.message()
    async def anything_else(message: Message):
        await message.answer(HELP_TEXT, reply_markup=ReplyKeyboardRemove())

    return dp


class Command(BaseCommand):
    help = "Запустить бота входа @priceIAPRO_bot"

    def handle(self, *args, **options):
        from aiogram import Bot

        if not settings.PRICE_BOT_TOKEN:
            self.stderr.write("PRICE_BOT_TOKEN не задан")
            return
        bot = Bot(settings.PRICE_BOT_TOKEN)
        dp = build_dispatcher()
        log.info("Бот входа запущен")
        asyncio.run(dp.start_polling(bot, allowed_updates=["message"]))
