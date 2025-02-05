import discord
import json
import asyncio
import os
import pytz
from dotenv import load_dotenv
from discord.ext import commands, tasks
from datetime import datetime, timezone, timedelta

print(r"""
 ____              __
/ __ \____ _____  / /____  _____
/ /_/ / __ `/ __ \/ __/ _ \/ ___/
/ _, _/ /_/ / /_/ / /_/  __/ /
/_/ |_|\__,_/ .___/\__/\___/_/
          /_/


Email me for support: support@rapter.is-a.dev
""")

intents = discord.Intents.default()
intents.guilds = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Define the desired timezone
TIMEZONE = pytz.timezone('America/New_York')

# Define the desired json file
DATA_FILE = "events.json"

#Load env file
load_dotenv()

# Load or initialize event data
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

event_data = load_data()

# Format datetime to 'MM/DD/YYYY hh:mm:ss AM/PM' and apply the time zone
def format_datetime(dt):
    # Convert the UTC time to New York time
    local_time = dt.astimezone(TIMEZONE)
    return local_time.strftime('%m/%d/%Y %I:%M:%S %p')  # Format as MM/DD/YYYY hh:mm:ss AM/PM

# Command to manually start an event
@bot.command()
async def start_event(ctx, event_name: str):
    # Get the current time in New York time zone
    start_time = datetime.now(timezone.utc).astimezone(TIMEZONE)

    # Calculate when the channel should be deleted (24 hours after the event starts)
    delete_after = start_time + timedelta(hours=24)

    # Save the event data
    event_data[str(ctx.message.id)] = {
        "guild_id": ctx.guild.id,
        "channel_id": None,
        "start_time": format_datetime(start_time),
        "delete_after": format_datetime(delete_after)
    }

    # Create event channel
    await create_event_channel(ctx.guild, event_name, start_time, delete_after)

    # Save the event data to file
    save_data(event_data)
    await ctx.send(f"Event '{event_name}' started at {format_datetime(start_time)}.")

@bot.event
async def on_scheduled_event_create(event):
    guild = event.guild
    if not guild:
        return

    start_time = event.start_time
    now = datetime.now(timezone.utc)

    # Calculate the time to delete the channel, 24 hours after event's start_time
    delete_after = start_time + timedelta(hours=24)

    if (start_time - now).total_seconds() <= 300:
        # If the event is starting soon, create the channel immediately
        await create_event_channel(guild, event.name, start_time, delete_after)
    else:
        # Save event details to file with the calculated deletion time
        event_data[str(event.id)] = {
            "guild_id": guild.id,
            "channel_id": None,
            "start_time": format_datetime(start_time),
            "delete_after": format_datetime(delete_after)
        }
        save_data(event_data)

@bot.event
async def on_scheduled_event_update(before, after):
    guild = after.guild
    if not guild:
        return

    # If the event is marked as active and doesn't have a channel, create it
    if before.status != discord.ScheduledEventStatus.active and after.status == discord.ScheduledEventStatus.active:
        await create_event_channel(guild, after.name, after.start_time, after.start_time + timedelta(hours=24))

    if after.status == discord.ScheduledEventStatus.completed:
        # Schedule channel deletion if event has been completed
        await schedule_channel_deletion(after.id)

async def create_event_channel(guild, event_name, start_time, delete_after):
    category = discord.utils.get(guild.categories, name="Events")
    if category is None:
        category = await guild.create_category("Events")

    # Create the channel name
    channel_name = f"event-{event_name.lower().replace(' ', '-')}"
    channel = await guild.create_text_channel(name=channel_name, category=category)

    # Save event data
    if str(event_name) not in event_data:
        event_data[str(event_name)] = {
            "guild_id": guild.id,
            "channel_id": channel.id,
            "start_time": format_datetime(start_time),
            "delete_after": format_datetime(delete_after)
        }
    else:
        event_data[str(event_name)]["channel_id"] = channel.id

    save_data(event_data)

async def schedule_channel_deletion(event_id):
    # If an event is completed, calculate the time for deletion
    if str(event_id) in event_data:
        event_data[str(event_id)]["delete_after"] = (datetime.now(timezone.utc) + timedelta(hours=24)).astimezone(TIMEZONE).strftime('%m/%d/%Y %I:%M:%S %p')
        save_data(event_data)

@tasks.loop(minutes=1)
async def check_events():
    # Get current time in New York timezone
    now = datetime.now(timezone.utc).astimezone(TIMEZONE)
    to_delete = []

    # Loop through event data and check for ongoing events
    for event_id, data in event_data.items():
        if "delete_after" in data:
            try:
                # Parse delete_after time from string and localize it to New York timezone
                delete_after = datetime.strptime(data["delete_after"], '%m/%d/%Y %I:%M:%S %p')
                delete_after = TIMEZONE.localize(delete_after)

                # If the delete_after time has passed, delete the channel
                if delete_after <= now:
                    guild = bot.get_guild(data["guild_id"])
                    if guild:
                        channel = guild.get_channel(data["channel_id"])
                        if channel:
                            await channel.delete()
                    to_delete.append(event_id)
            except ValueError:
                # Handle invalid date format
                print(f"Invalid date format for event {event_id}: {data['delete_after']}")

        # Check if event end time is available and if event has ended
        if "start_time" in data and "end_time" in data:
            try:
                # Parse event start and end times
                start_time = datetime.strptime(data["start_time"], '%m/%d/%Y %I:%M:%S %p')
                end_time = datetime.strptime(data["end_time"], '%m/%d/%Y %I:%M:%S %p')

                # Localize both times to New York timezone
                start_time = TIMEZONE.localize(start_time)
                end_time = TIMEZONE.localize(end_time)

                # Check if the event has ended and is past the 24-hour delete window
                if end_time <= now and (now - end_time).total_seconds() >= 86400:
                    # Event has ended and it's been more than 24 hours
                    guild = bot.get_guild(data["guild_id"])
                    if guild:
                        channel = guild.get_channel(data["channel_id"])
                        if channel:
                            await channel.delete()
                    to_delete.append(event_id)

            except ValueError:
                # Handle invalid date format
                print(f"Invalid date format for event {event_id}: {data['start_time']} or {data['end_time']}")

    # Remove deleted events from the data
    for event_id in to_delete:
        del event_data[event_id]

    # Save updated event data
    save_data(event_data)

@bot.event
async def on_ready():
    print(f"{bot.user} is online!")
    check_events.start()

# Run the bot with the specified token
bot.run(os.getenv("bot_token"))