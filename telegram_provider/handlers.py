import logging
from ctypes import ArgumentError
from typing import TYPE_CHECKING

import requests
from django.conf import settings
from telegram import Update
from telegram.constants import ReactionEmoji

from common.models import User, UserVerificationCode
from operation.models import Line, Vehicle
from spotting.enums import (
    SpottingDataSource,
    SpottingEventType,
    SpottingVehicleStatus,
    SpottingWheelStatus,
)
from spotting.models import Event, EventSource
from telegram_provider.parsers import spotting_parser
from telegram_provider.utils import infinite_retry_on_error

if TYPE_CHECKING:
    from telegram.ext import ContextTypes

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
# set higher logging level for httpx to avoid all GET and POST requests being logged
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


async def error_handler(update: object, context: "ContextTypes.DEFAULT_TYPE") -> None:
    update: "Update"
    print(update)
    print(context.error)
    # """Log the error and send a telegram message to notify the developer."""
    # # Log the error before we do anything else, so we can see it even if something breaks.
    # logger.error("Exception while handling an update:", exc_info=context.error)

    # # traceback.format_exception returns the usual python message about an exception, but as a
    # # list of strings rather than a single string, so we have to join them together.
    # tb_list = traceback.format_exception(
    #     None, context.error, context.error.__traceback__
    # )
    # tb_string = "".join(tb_list)

    # # Build the message with some markup and additional information about what happened.
    # # You might need to add some logic to deal with messages longer than the 4096 character limit.
    # update_str = update.to_dict() if isinstance(update, Update) else str(update)
    # message = (
    #     "An exception was raised while handling an update\n"
    #     f"<pre>update = {html.escape(json.dumps(update_str, indent=2, ensure_ascii=False))}"
    #     "</pre>\n\n"
    #     f"<pre>context.chat_data = {html.escape(str(context.chat_data))}</pre>\n\n"
    #     f"<pre>context.user_data = {html.escape(str(context.user_data))}</pre>\n\n"
    #     f"<pre>{html.escape(tb_string)}</pre>"
    # )

    # # Finally, send the message
    # # TODO: Fix this
    # await context.bot.send_message(
    #     chat_id="DEVELOPER_CHAT_ID", text=message, parse_mode=ParseMode.HTML
    # )


async def help(update: Update, context) -> None:
    """Display a message with instructions on how to use this bot."""
    command_description_dict = {
        "/ping": "Checks if the bot is still alive and kicking.",
        "/verify [code]": "Enter the verification code to link your telegram account with your Google Account.",
    }

    text = "Command List: \n"
    for k, v in command_description_dict.items():
        text += f"<code>{k}</code> - {v}\n"
    await update.message.reply_html(text=text)


async def dad_joke(update: Update, context) -> None:
    response = requests.get(
        url="https://icanhazdadjoke.com/",
        headers={
            "Accept": "text/plain",
            "User-Agent": "MLPTF Community Bot (https://github.com/kwongtn/lift-rosak-backend)",
        },
    )
    await update.message.reply_text(response.text)


async def ping(update: Update, context) -> None:
    """Reacts to the sent message to prove that bot is alive and kicking."""
    try:
        await update.message.set_reaction(ReactionEmoji.THUMBS_UP)
    except Exception as e:
        print(e)
    # set_telegram_reaction.apply_async(
    #     kwargs={
    #         "update_payload": update.to_json(),
    #         "reaction": ReactionEmoji.THUMBS_UP,
    #         # "pickled_bot": pickle.dumps(update.get_bot()),
    #         "pickled_update": pickle.dumps(update),
    #         "bot_payload": update.get_bot().to_json(),
    #     }
    # )


async def verify(update: Update, context) -> None:
    splitted = update.message.text.split(" ")
    if len(splitted) != 2 or len(splitted[1]) != 6:
        await update.message.reply_html(
            text=(
                "Please submit according to the following syntax:\n"
                "<code>/verify [6 digit code]</code> \n"
                'The code is a 6 digit number obtainable from the side panel at the <a href="https://community.mlptf.org.my">TranSPOT</a> site, or you may visit <a href="https://github.com/kwongtn/rosak_firebase/wiki/Linking-to-Telegram">our wiki<a/> for a detailed tutorial.'
            )
        )
        return

    code = update.message.text.split(" ")[1]

    # If code is invalid, send an error
    code_obj = await UserVerificationCode.objects.filter(code=int(code)).afirst()
    if code_obj is None:
        await update.message.reply_html(
            text="Verification code is invalid. Please try again."
        )
        return

    # Else link to account
    user: User = await User.objects.aget(id=code_obj.user_id)
    user.telegram_id = update.message.from_user.id
    await user.asave()
    await code_obj.adelete()

    await update.message.reply_html(
        text=f"🎉 Success! Account linked to <code>{user.display_name}</code>. Happy spotting!"
    )


async def help_spotting(update: Update, context) -> None:
    parser = spotting_parser()

    await update.message.reply_html(
        text=parser.format_help(),
    )


async def spot(update: Update, context) -> None:
    # Check if user has verified account
    user = await User.objects.filter(telegram_id=update.message.from_user.id).afirst()

    env_url_dict = {
        "local": "localhost:4200",
        "staging": "rosak-7223b--staging-jflqbzzi.web.app",
        "production": "community.mlptf.org.my",
    }

    # If no, send error and ask user to verify before proceeding
    if user is None:
        await update.message.reply_html(
            text=f'Please use the <code>/verify [code]</code> command to verify your telegram account before proceeding. You may obtain the code from the <a href="{env_url_dict.get(settings.ENVIRONMENT)}">TranSPOT</a> site, or visit <a href="https://github.com/kwongtn/rosak_firebase/wiki/Linking-to-Telegram">our wiki<a/> for a detailed tutorial.'
        )
        return

    # Else, parse syntax
    parser = spotting_parser()
    args = None
    try:
        args = parser.parse_args(update.message.text.split(" ")[1:])
        # await update.message.reply_text(text=str(args))
    except ArgumentError as e:
        print(e)
        await infinite_retry_on_error(
            update.message.set_reaction, ReactionEmoji.THUMBS_DOWN
        )
        raise e

    try:
        # If syntax is correct, create entry accordingly, then react thumbs up

        # Search for line
        lines = Line.objects.filter(telegram_channel_id=update.effective_chat.id)

        if not await lines.aexists():
            error_text = "No line assigned for this channel."
            await update.message.reply_html(text=error_text)
            raise Exception(error_text)

        # Search for vehicle
        vehicle = await Vehicle.objects.filter(
            identification_no=args.vehicle_number,
            lines__in=lines,
        ).afirst()

        if vehicle is None:
            error_text = (
                f"No vehicle found with the number <code>{args.vehicle_number}</code>"
            )
            await update.message.reply_html(text=error_text)
            raise Exception(error_text)

        wheel_status_map = {
            1: SpottingWheelStatus.FRESH,
            2: SpottingWheelStatus.NEAR_PERFECT,
            3: SpottingWheelStatus.FLAT,
            4: SpottingWheelStatus.WORN_OUT,
            5: SpottingWheelStatus.WORRYING,
        }
        status_map = {
            1: SpottingVehicleStatus.IN_SERVICE,
            2: SpottingVehicleStatus.NOT_IN_SERVICE,
            3: SpottingVehicleStatus.DECOMMISSIONED,
            4: SpottingVehicleStatus.TESTING,
        }

        notes = args.notes or ""
        if isinstance(notes, list):
            notes = " ".join(notes)

        event_source = await EventSource.objects.filter(
            name=SpottingDataSource.TELEGRAM
        ).afirst()
        event = Event(
            spotting_date=update.message.date,
            reporter_id=user.id,
            vehicle_id=vehicle.id,
            is_anonymous=args.anon,
            notes=notes,
            status=status_map[args.status],
            type=SpottingEventType.JUST_SPOTTING,
            data_source_id=event_source.id,
        )

        if args.wheel_status:
            event.wheel_status = wheel_status_map[args.wheel_status]

        # TODO: Location to determine spotting type

        await event.asave()
        await infinite_retry_on_error(
            update.message.set_reaction, ReactionEmoji.THUMBS_UP
        )

    except Exception as e:
        print(e)
        await infinite_retry_on_error(
            update.message.set_reaction, ReactionEmoji.THUMBS_DOWN
        )
        raise e
