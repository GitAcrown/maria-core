"""Menus Components v2 comme dans MARIA_R : un conteneur, un état, `build()` à chaque clic."""

import logging
from collections.abc import Awaitable, Callable, Sequence

import discord

from maria_core.discord.layout import emojis, quiet_links

logger = logging.getLogger(__name__)

NO_PINGS = discord.AllowedMentions.none()
MENU_TIMEOUT = 840.0

type Run = Callable[[discord.Interaction], Awaitable[None]]
type Pick = Callable[[discord.Interaction, str], Awaitable[None]]


class Hub(discord.ui.LayoutView):
    """Base des menus éphémères. Seule la personne qui l'a ouvert peut cliquer."""

    def __init__(
        self, *, viewer_id: int, timeout: float | None = MENU_TIMEOUT, host: "Hub | None" = None
    ) -> None:
        super().__init__(timeout=timeout)
        self.viewer_id = viewer_id
        self.host = host  # un panneau est dessiné par son hôte, qui garde les onglets
        self.message: discord.InteractionMessage | None = None

    def build(self) -> None:
        raise NotImplementedError

    def set_layout(
        self,
        body: Sequence[discord.ui.Item],
        *rows: discord.ui.ActionRow,
        above: Sequence[discord.ui.Item] = (),
    ) -> None:
        """Comme dans CRIT : les onglets (`above`) au-dessus de la carte, puis, dans un seul
        conteneur, le contenu, un trait fin et les contrôles."""
        children = list(body)
        if rows:
            children.append(thin())
            children.extend(rows)
        card = discord.ui.Container(*children)
        if self.host is not None:
            self.host.place([card])
        else:
            self.place([*above, card])

    def place(self, items: Sequence[discord.ui.Item]) -> None:
        self.clear_items()
        for item in items:
            self.add_item(item)

    async def open(self, interaction: discord.Interaction) -> None:
        self.build()
        if interaction.response.is_done():
            await interaction.followup.send(view=self, ephemeral=True, allowed_mentions=NO_PINGS)
        else:
            await interaction.response.send_message(
                view=self, ephemeral=True, allowed_mentions=NO_PINGS
            )
        try:
            self.message = await interaction.original_response()
        except discord.HTTPException:
            self.message = None

    async def refresh(self, interaction: discord.Interaction) -> None:
        if self.host is not None:
            await self.host.refresh(interaction)
            return
        self.build()
        if interaction.response.is_done():
            await interaction.edit_original_response(view=self, allowed_mentions=NO_PINGS)
        else:
            await interaction.response.edit_message(view=self, allowed_mentions=NO_PINGS)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.viewer_id:
            return True
        await interaction.response.send_message(
            "**Action impossible ·** Ce menu ne s'affiche que pour toi.",
            ephemeral=True,
            delete_after=10,
        )
        return False

    async def on_error(
        self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item
    ) -> None:
        logger.error("Menu %s en échec", type(self).__name__, exc_info=error)
        text = "**Erreur ·** Le bouton a planté. Réessaie."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(text, ephemeral=True)
            else:
                await interaction.response.send_message(text, ephemeral=True)
        except discord.HTTPException:
            logger.debug("Erreur de menu non signalée", exc_info=True)

    async def on_timeout(self) -> None:
        for item in self.walk_children():
            if isinstance(item, discord.ui.Button | discord.ui.Select):
                item.disabled = True
        if self.message is None:
            return
        try:
            await self.message.edit(view=self, allowed_mentions=NO_PINGS)
        except discord.HTTPException:
            logger.debug("Menu expiré non modifié", exc_info=True)


class Action(discord.ui.Button):
    """Un bouton qui appelle une fonction : évite une classe par bouton."""

    def __init__(
        self,
        label: str,
        run: Run,
        *,
        style: discord.ButtonStyle = discord.ButtonStyle.secondary,
        disabled: bool = False,
    ) -> None:
        super().__init__(label=label, style=style, disabled=disabled)
        self.run = run

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.run(interaction)


class Tab(discord.ui.Button):
    """Un onglet : l'actif est en bleu, les autres en gris, avec un emoji comme dans CRIT."""

    def __init__(self, label: str, run: Run, *, active: bool, emoji: str = "") -> None:
        mark = emojis(emoji) if emoji else ""
        super().__init__(
            label=label or None,
            emoji=discord.PartialEmoji.from_str(mark) if mark else None,
            style=discord.ButtonStyle.primary if active else discord.ButtonStyle.secondary,
        )
        self.run = run

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.run(interaction)


def tab_bar(tabs: Sequence[Tab]) -> list[discord.ui.Item]:
    """La rangée d'onglets, à passer en `above` ; rien s'il n'y a pas de choix à faire."""
    return [discord.ui.ActionRow(*tabs[:5])] if len(tabs) > 1 else []


def arrows(page: int, total: int, turn: Callable[[int], Run]) -> list[discord.ui.Item]:
    """← et → de la pagination, absents quand tout tient sur une page."""
    if total <= 1:
        return []
    return [
        Action("←", turn(-1), disabled=page <= 0),
        Action("→", turn(1), disabled=page >= total - 1),
    ]


async def refuse(interaction: discord.Interaction, reason: str) -> None:
    """Refus éphémère qui s'efface seul, comme dans CRIT."""
    await interaction.response.send_message(
        f"**Action impossible ·** {reason}", ephemeral=True, delete_after=10
    )


class Picker(discord.ui.Select):
    def __init__(self, placeholder: str, options: list[discord.SelectOption], run: Pick) -> None:
        super().__init__(placeholder=placeholder, options=options[:25])
        self.run = run

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.run(interaction, self.values[0])


def title(text: str, meta: str = "") -> discord.ui.TextDisplay:
    """Titre `##` et ligne `-#` dans le même bloc."""
    head = emojis(text)
    if not meta:
        return discord.ui.TextDisplay(f"## {head}")
    return discord.ui.TextDisplay(f"## {head}\n-# {emojis(meta)}")


def body(text: str) -> discord.ui.TextDisplay:
    return discord.ui.TextDisplay(quiet_links(text.strip()[:3900]) or "-# (vide)")


def wide() -> discord.ui.Separator:
    return discord.ui.Separator(spacing=discord.SeparatorSpacing.large)


def thin() -> discord.ui.Separator:
    return discord.ui.Separator(spacing=discord.SeparatorSpacing.small)


def option(
    value: int | str, label: str, description: str = "", emoji: str = ""
) -> discord.SelectOption:
    shown = " ".join(label.split())[:100] or str(value)
    mark = emojis(emoji) if emoji else ""
    return discord.SelectOption(
        label=shown,
        value=str(value),
        description=" ".join(description.split())[:100] or None,
        emoji=mark or None,
    )


def clip(text: str, limit: int) -> str:
    flat = " ".join((text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def pages(count: int, size: int) -> int:
    return max(1, (count + size - 1) // size)


def card(heading: str, text: str = "", *, meta: str = "") -> discord.ui.LayoutView:
    """Réponse simple d'une commande : un titre, un trait, le contenu."""
    view = discord.ui.LayoutView(timeout=None)
    items: list[discord.ui.Item] = [title(heading, meta)]
    if text.strip():
        items += [wide(), body(text)]
    view.add_item(discord.ui.Container(*items))
    return view


async def say(ctx: object, heading: str, text: str = "", *, meta: str = "") -> None:
    """Réponse d'une commande à préfixe, en carte comme les commandes slash."""
    send = getattr(ctx, "send")  # noqa: B009
    await send(view=card(heading, text, meta=meta), allowed_mentions=NO_PINGS)


async def answer(
    interaction: discord.Interaction, heading: str, text: str = "", *, meta: str = ""
) -> None:
    """Réponse éphémère d'une commande, en carte."""
    view = card(heading, text, meta=meta)
    if interaction.response.is_done():
        await interaction.followup.send(view=view, ephemeral=True, allowed_mentions=NO_PINGS)
    else:
        await interaction.response.send_message(
            view=view, ephemeral=True, allowed_mentions=NO_PINGS
        )
