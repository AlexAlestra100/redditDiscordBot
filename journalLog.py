import argparse
import sys
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
import discord
from typing import List, Optional, Tuple

# Debug helper removed; keep code output minimal in production

# Auto-delete delays (seconds)
AUTO_DELETE_DELAY = 5
GET_RESULT_DELETE_DELAY = 30

try:
	from discord.ext import commands
except Exception:
	commands = None  # Optional import for Discord Cog


def timestamp_str() -> str:
	dt = datetime.now().astimezone()
	tz_abbr = dt.tzname() or ""
	# Example: 2025-12-11 Thu 14:23:11 -0500 (EST)
	base = dt.strftime("%Y-%m-%d %a %H:%M:%S %z")
	return f"{base} ({tz_abbr})" if tz_abbr else base


def _ensure_db(db_path: Path) -> None:
	db_path.parent.mkdir(parents=True, exist_ok=True)
	with sqlite3.connect(db_path) as conn:
		conn.execute(
			"""
			CREATE TABLE IF NOT EXISTS journal (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				user_id TEXT NOT NULL,
				created_at TEXT NOT NULL,
				created_at_epoch INTEGER,
				timezone TEXT,
				content TEXT NOT NULL
			)
			"""
		)
		# Ensure epoch column exists (for reliable time range queries)
		try:
			conn.execute("ALTER TABLE journal ADD COLUMN created_at_epoch INTEGER")
		except sqlite3.OperationalError:
			pass
		# Backfill epoch for existing rows where missing
		try:
			cur = conn.execute("SELECT id, created_at FROM journal WHERE created_at_epoch IS NULL")
			rows = cur.fetchall()
			for _id, created_at_iso in rows:
				try:
					dt = datetime.fromisoformat(created_at_iso)
				except Exception:
					# Attempt to parse common formats
					try:
						dt = datetime.strptime(created_at_iso, "%Y-%m-%d %H:%M:%S%z")
					except Exception:
						dt = None
				if dt is not None:
					conn.execute(
						"UPDATE journal SET created_at_epoch = ? WHERE id = ?",
						(int(dt.timestamp()), _id),
					)
		except Exception:
			pass


def add_entry_db(db_path: Path, user_id: str, content: str) -> None:
	_ensure_db(db_path)
	# Capture server-local timestamp when creating the entry
	dt = datetime.now().astimezone()
	epoch = int(dt.timestamp())
	# We store the ISO timestamp (with server tz) and the epoch seconds (UTC-based)
	with sqlite3.connect(db_path) as conn:
		conn.execute(
			"INSERT INTO journal (user_id, created_at, created_at_epoch, timezone, content) VALUES (?, ?, ?, ?, ?)",
			(user_id, dt.isoformat(), epoch, dt.tzname() or "", content.strip()),
		)


def get_entries_db(
	db_path: Path,
	requester_id: str,
	admin_id: Optional[str],
	target_user_id: Optional[str] = None,
	date_str: Optional[str] = None,
	days_ago: Optional[int] = None,
) -> List[Tuple[int, str, Optional[int], str, str]]:
	_ensure_db(db_path)
	where = []
	params: List[object] = []

	# Access control: non-admins can only see their own entries
	if admin_id and requester_id == admin_id:
		if target_user_id:
			where.append("user_id = ?")
			params.append(target_user_id)
	else:
		where.append("user_id = ?")
		params.append(requester_id)

	if date_str:
		# Build local-day range using epoch to avoid TZ parsing issues in SQLite
		try:
			day_start = datetime.fromisoformat(date_str + "T00:00:00").astimezone()
			day_end = day_start + timedelta(days=1)
			where.append("created_at_epoch >= ? AND created_at_epoch < ?")
			params.extend([int(day_start.timestamp()), int(day_end.timestamp())])
		except Exception:
			# Fallback to textual comparison if parsing fails
			where.append("date(created_at) = ?")
			params.append(date_str)

	if days_ago is not None:
		# Entries since now minus N days (inclusive)
		since = datetime.now().astimezone() - timedelta(days=days_ago)
		where.append("created_at_epoch >= ?")
		params.append(int(since.timestamp()))

	# Include created_at_epoch so formatting can reliably convert to local time
	sql = "SELECT id, user_id, created_at_epoch, created_at, content FROM journal"
	if where:
		sql += " WHERE " + " AND ".join(where)
	sql += " ORDER BY datetime(created_at) DESC"

	with sqlite3.connect(db_path) as conn:
		cur = conn.execute(sql, params)
		return [(row[0], row[1], row[2], row[3], row[4]) for row in cur.fetchall()]


def get_distinct_user_ids(db_path: Path) -> List[str]:
	_ensure_db(db_path)
	with sqlite3.connect(db_path) as conn:
		cur = conn.execute("SELECT DISTINCT user_id FROM journal ORDER BY user_id")
		return [row[0] for row in cur.fetchall()]


def format_entry_row(row: Tuple[int, str, Optional[int], str, str], username: Optional[str] = None) -> str:
	_id, user_id, created_at_epoch, created_at_iso, content = row
	dt = None
	# Prefer the stored ISO timestamp (it contains server tz when added)
	if created_at_iso:
		try:
			dt = datetime.fromisoformat(created_at_iso)
		except Exception:
			try:
				dt = datetime.strptime(created_at_iso, "%Y-%m-%d %H:%M:%S%z")
			except Exception:
				dt = None

	# If we couldn't parse the ISO, fall back to epoch if available
	if dt is None and created_at_epoch is not None:
		try:
			# created_at_epoch represents seconds since the epoch (UTC)
			dt = datetime.fromtimestamp(int(created_at_epoch), tz=timezone.utc).astimezone()
		except Exception:
			dt = None

	ts = dt.strftime("%Y-%m-%d %a %I:%M:%S %p") if dt is not None else (created_at_iso or "")

	# Display the stored username when available, otherwise show the raw uid
	user_label = username if username else user_id
	# New format: username, datetime, journal entry
	return f"{user_label}\n{ts}\n\n{content}\n"


def _normalize_user_id(user_id: Optional[str]) -> Optional[str]:
	if not user_id:
		return user_id
	# Convert mention formats like <@123> or <@!123> to plain numeric id
	if user_id.startswith("<@") and user_id.endswith(">"):
		inner = user_id[2:-1]
		if inner.startswith("!"):
			inner = inner[1:]
		return inner
	return user_id


def _parse_prefix_options(content: str) -> Tuple[Optional[str], Optional[int], Optional[str], Optional[int]]:
	# Parse tokens like: date:YYYY-MM-DD days:N user:ID entries:N
	date = None
	days = None
	user = None
	entries = None
	for token in content.split():
		if token.startswith("date:"):
			date = token[len("date:"):]
		elif token.startswith("days:"):
			try:
				days = int(token[len("days:"):])
			except Exception:
				pass
		elif token.startswith("user:"):
			user = token[len("user:"):]
		elif token.startswith("entries:"):
			try:
				entries = int(token[len("entries:"):])
			except Exception:
				pass
	return date, days, user, entries


def read_entry_interactive() -> str:
	print("Enter your journal entry. Finish with an empty line:")
	lines = []
	while True:
		try:
			line = input()
		except EOFError:
			break
		if line.strip() == "":
			break
		lines.append(line)
	return "\n".join(lines).strip()


def read_entry_from_stdin() -> str:
	data = sys.stdin.read()
	return data.strip()


def parse_args(argv=None):
	parser = argparse.ArgumentParser(
		description="Append a journal entry with local timezone timestamp to a text file.",
	)
	parser.add_argument(
		"-e",
		"--entry",
		help="Journal entry text. If omitted, reads from stdin if piped or prompts interactively.",
	)
	parser.add_argument(
		"-d",
		"--db",
		default="journal.db",
		help="SQLite database file path (default: journal.db).",
	)
	parser.add_argument(
		"-u",
		"--user",
		help="User ID for the entry (required for CLI add).",
	)
	parser.add_argument(
		"--get-date",
		help="Retrieve entries for calendar date (YYYY-MM-DD).",
	)
	parser.add_argument(
		"--get-days",
		type=int,
		help="Retrieve entries since N days ago.",
	)
	parser.add_argument(
		"--target-user",
		help="Admin-only: target user ID for retrieval.",
	)
	parser.add_argument(
		"--admin-id",
		help="Admin user ID for access control in retrieval.",
	)
	return parser.parse_args(argv)


def main(argv=None) -> int:
	args = parse_args(argv)
	db_file = Path(args.db)

	# Retrieval mode
	if args.get_date or args.get_days is not None:
		requester = args.user or "cli"
		rows = get_entries_db(
			db_file,
			requester_id=requester,
			admin_id=args.admin_id,
			target_user_id=args.target_user,
			date_str=args.get_date,
			days_ago=args.get_days,
		)
		if not rows:
			print("No matching entries.")
			return 0
		for row in rows:
			print(format_entry_row(row))
		return 0

	# Add mode
	entry = args.entry
	if not entry:
		if not sys.stdin.isatty():
			entry = read_entry_from_stdin()
		else:
			entry = read_entry_interactive()
	if not entry:
		print("No entry text provided. Aborting.")
		return 1
	if not args.user:
		print("--user is required to add an entry via CLI.")
		return 1

	add_entry_db(db_file, args.user, entry)
	print(f"Appended entry for user {args.user} to {db_file}")
	return 0


if commands is not None:
	class JournalCog(commands.Cog):  # type: ignore
		def __init__(self, bot, db_path: Path, admin_id: Optional[str] = None):
			self.bot = bot
			self.db_path = db_path
			self.admin_id = admin_id

		class _JournalModal(discord.ui.Modal):
			def __init__(self, db_path: Path):
				super().__init__(title="Journal entry")
				self.db_path = db_path
				self.entry = discord.ui.TextInput(label="Entry", style=discord.TextStyle.long, required=True, max_length=4000)
				self.add_item(self.entry)

			async def on_submit(self, interaction: discord.Interaction) -> None:  # type: ignore
				add_entry_db(self.db_path, str(interaction.user.id), self.entry.value)
				try:
					await interaction.response.send_message("Journal entry saved.", ephemeral=True)
				except Exception:
					pass

		@commands.command(name="journal")
		async def journal(self, ctx):
			author_id = str(ctx.author.id)
			# For prefix command, take whatever follows the command as the entry
			entry: Optional[str] = None
			if ctx.message:
				msg_content = ctx.message.content or ""
				parts = msg_content.split(maxsplit=1)
				entry = parts[1] if len(parts) > 1 else None

			# If no trailing text, delete the invoking message when possible and return
			if not entry:
				try:
					if ctx.message and ctx.channel.permissions_for(ctx.guild.me).manage_messages:
						await ctx.message.delete()
				except Exception:
					pass
				return

			# Save entry
			add_entry_db(self.db_path, author_id, entry)

			# Prefix behavior: delete the invoking message (if possible) and show a short confirmation
			try:
				if ctx.message and ctx.channel.permissions_for(ctx.guild.me).manage_messages:
					await ctx.message.delete()
			except Exception:
				pass
			try:
				confirm = await ctx.send("Journal entry saved.")
				await confirm.delete(delay=AUTO_DELETE_DELAY)
			except Exception:
				pass

		# Use app_commands for slash option descriptions
		from discord import app_commands

		@commands.hybrid_command(name="journal_get")
		@app_commands.describe(
			date="Calendar date (YYYY-MM-DD)",
			days="Entries since N days ago (0 = today)",
			user="Admin only: target user ID",
			entries="Number of entries to return (default 5)",
		)
		async def journal_get(
			self,
			ctx,
			date: Optional[str] = None,
			days: Optional[int] = None,
			user: Optional[str] = None,
			entries: Optional[int] = None,
		):
			requester = str(ctx.author.id)
			# Normalize admin and user ids
			admin_id_norm = _normalize_user_id(self.admin_id)
			user = _normalize_user_id(user)

			# If invoked via prefix, ignore discord's positional mapping and parse tokens ourselves
			if getattr(ctx, "interaction", None) is None and ctx.message:
				msg_content = ctx.message.content or ""
				# Remove the command name
				parts = msg_content.split(maxsplit=1)
				arg_text = parts[1] if len(parts) > 1 else ""
				p_date, p_days, p_user, p_entries = _parse_prefix_options(arg_text)
				date = p_date
				days = p_days
				user = p_user
				if p_entries is not None:
					entries = p_entries

			# If requester isn't admin, ignore any user filter
			if requester != (admin_id_norm or ""):
				user = None
			rows = get_entries_db(
				self.db_path,
				requester_id=requester,
				admin_id=admin_id_norm,
				target_user_id=user,
				date_str=date,
				days_ago=days,
			)
			# Debug logs removed
			if not rows:
				# Ephemeral for slash, short message for prefix
				if getattr(ctx, "interaction", None) is not None:
					if ctx.interaction.response.is_done():
						await ctx.interaction.followup.send("No matching journal entries.", ephemeral=True)
					else:
						await ctx.interaction.response.send_message("No matching journal entries.", ephemeral=True)
				else:
					msg = await ctx.send("No matching journal entries.")
					try:
						await msg.delete(delay=AUTO_DELETE_DELAY)
					except Exception:
						pass
				return
			# Determine how many rows to show. Default is 5; entries<=0 means show all
			if entries is None:
				max_rows = 5
			elif entries <= 0:
				max_rows = len(rows)
			else:
				max_rows = entries
			shown = rows[:max_rows]
			# Resolve user ids to readable names where possible to improve output
			user_ids = {r[1] for r in shown}
			user_map = {}
			for uid in user_ids:
				try:
					int_uid = int(uid)
				except Exception:
					user_map[uid] = uid
					continue
				user = None
				# try cache via get_user
				try:
					user = self.bot.get_user(int_uid) if hasattr(self, 'bot') else None
				except Exception:
					user = None
				if user is None:
					try:
						user = await self.bot.fetch_user(int_uid)  # type: ignore
					except Exception:
						user = None
				user_map[uid] = str(user) if user is not None else uid
			text = "\n\n".join(format_entry_row(r, username=user_map.get(r[1])) for r in shown)
			suffix = "" if len(rows) <= max_rows else f"\n...and {len(rows) - max_rows} more."
			# Ephemeral for slash, auto-delete for prefix
			if getattr(ctx, "interaction", None) is not None:
				if ctx.interaction.response.is_done():
					await ctx.interaction.followup.send(text + suffix, ephemeral=True)
				else:
					await ctx.interaction.response.send_message(text + suffix, ephemeral=True)
			else:
				msg = await ctx.send(text + suffix)
				try:
					await msg.delete(delay=GET_RESULT_DELETE_DELAY)
				except Exception:
					pass

		@journal_get.autocomplete("user")
		async def journal_get_user_autocomplete(
			self,
			interaction,
			current: str,
		):
			# Only admin gets user suggestions
			try:
				author_id = str(interaction.user.id)
			except Exception:
				return []
			admin_id_norm = _normalize_user_id(self.admin_id)
			if author_id != (admin_id_norm or ""):
				return []
			from discord import app_commands as ac
			# Suggest distinct user_ids from DB filtered by current prefix
			user_ids = get_distinct_user_ids(self.db_path)
			if current:
				user_ids = [u for u in user_ids if u.startswith(current)]
			# Limit suggestions
			suggestions = user_ids[:25]
			return [ac.Choice(name=u, value=u) for u in suggestions]
else:
	JournalCog = None  # type: ignore


if __name__ == "__main__":
	raise SystemExit(main())

