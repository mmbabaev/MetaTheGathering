from telegram import Update
from telegram.ext import ContextTypes

from bot.handlers.features import FeaturesHandler
from bot.registration_messages import RegistrationMessageRefreshJob
from core.database import SessionLocal
from services.feature_flags import KNOWN_FLAGS, FeatureFlags, FeatureFlagService
from services.user import UserService


def _features_handler(db) -> FeaturesHandler:
    return FeaturesHandler(UserService(db), FeatureFlagService(db))


async def cmd_features(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    msg = update.effective_message
    if not user or not msg:
        return
    db = SessionLocal()
    try:
        result = _features_handler(db).handle_features_list(user.id)
        await msg.reply_text(result.text, reply_markup=result.keyboard)
    finally:
        db.close()


async def callback_feature_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return
    flag_name = query.data.split(":", 1)[1]
    meta = KNOWN_FLAGS.get(flag_name)
    text = meta.description if meta else flag_name
    await query.answer(text, show_alert=True)


async def callback_feature_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if not user or not query or not query.data:
        return
    flag_name = query.data.split(":", 1)[1]
    db = SessionLocal()
    try:
        result = _features_handler(db).handle_toggle_flag(user.id, flag_name)
        if result.is_alert:
            await query.answer(result.text, show_alert=True)
            return
        await query.edit_message_text(result.text, reply_markup=result.keyboard)
        await query.answer()
        if flag_name == FeatureFlags.LIVE_REGISTRATION_COUNT:
            await RegistrationMessageRefreshJob().run(context.bot, db=db)
    finally:
        db.close()
