import curses
from abc import ABC

from .config import CONFIG

try:
    import ueberzug.lib.v0 as ueberzug
except ImportError:
    ueberzug = None


class UnknownQueryStyle(Exception):
    """Indicates that the provided query style is not supported."""

    pass


class InstantiateIndicatorClassError(Exception):
    def __init__(self, message="Can't instantiate an indicator class!"):
        self.message = message
        super().__init__(message)


class IndicatorClass(ABC):
    """Parent to all indicator classes."""

    pass


class NoCanvas(IndicatorClass):
    def __exit__(self, dummy1, dummy2, dummy3):
        pass

    def __enter__(self):
        pass


class ReturnFromMenu(IndicatorClass):
    """Returned from menu method to indicate that application flow should step
    closer to the root menu.
    """

    pass


class QueryStyle(IndicatorClass):
    """Indicates whether selection query should return by index, item or both."""

    pass


class IndexQuery(QueryStyle):
    """Indicates that selection query should return by index."""

    pass


class ItemQuery(QueryStyle):
    """Indicates that selection query should return by item."""

    pass


class CombinedQuery(QueryStyle):
    """Indicates that selection query should return by both item and index."""

    pass


def wait_screen(message, wait_function, *args, **kwargs):
    """Display a message while the user waits for a function to execute."""
    return curses.wrapper(_wait_screen_ncurses, message, wait_function, *args, **kwargs)


def _wait_screen_ncurses(stdscr, message, wait_function, *args, **kwargs):
    """Ncurses level of do_wait_screen starts. It should never be called
    directly, but always through do_wait_screen.
    """
    curses.curs_set(0)
    curses.init_pair(CONFIG.HIGHLIGHTED, curses.COLOR_BLACK, curses.COLOR_WHITE)
    curses.init_pair(CONFIG.NOT_HIGHLIGHTED, curses.COLOR_WHITE, curses.COLOR_BLACK)
    print_menu(message, [], stdscr, 0, show_item_number=False)
    return wait_function(*args, **kwargs)


def yes_no_query(query):
    """Get a yes/no response to some query from the user."""
    return curses.wrapper(_yes_no_query_ncurses, query)


def _yes_no_query_ncurses(stdscr, query):
    """Ncurses level of do_yes_no_query, it should never be called directly,
    but always through do_yes_no_query.
    """
    return (
        _select_query_ncurses(stdscr, query, ["yes", "no"], show_item_number=False)
        == "yes"
    )


def select_query(
    query,
    options,
    query_style=ItemQuery,
    initial_index=None,
    show_item_number=True,
    adhoc_keys=None,
):
    """Display a list to the user to choose."""
    return curses.wrapper(
        _select_query_ncurses,
        query,
        options,
        query_style=query_style,
        initial_index=initial_index,
        show_item_number=show_item_number,
        adhoc_keys=adhoc_keys or [],
    )


def _select_query_ncurses(
    stdscr,
    query,
    options,
    query_style=ItemQuery,
    initial_index=None,
    show_item_number=True,
    adhoc_keys=None,
):
    """Ncurses level of do_selection, it should never be called directory but
    through do_selection_query.
    """
    curses.curs_set(0)
    curses.init_pair(CONFIG.HIGHLIGHTED, curses.COLOR_BLACK, curses.COLOR_WHITE)
    curses.init_pair(CONFIG.NOT_HIGHLIGHTED, curses.COLOR_WHITE, curses.COLOR_BLACK)
    jump_num_list = []
    if initial_index is not None:
        choice_index = initial_index
    else:
        choice_index = 0
    while True:
        with (ueberzug.Canvas() if CONFIG.USE_THUMBNAILS else NoCanvas()) as canvas:
            print_menu(
                query,
                options,
                stdscr,
                choice_index,
                show_item_number=show_item_number,
                jump_num_str="".join(jump_num_list),
                canvas=canvas,
            )
            key = stdscr.getch()
            # Ad hoc keys should always take first precedence

            if key in (adhoc_keys or []):
                for adhoc_key in adhoc_keys or []:
                    if adhoc_key.is_valid_index(choice_index):
                        if query_style is ItemQuery:
                            return adhoc_key.item
                        elif query_style is IndexQuery:
                            return choice_index
                        elif query_style is CombinedQuery:
                            return adhoc_key.item, choice_index

            elif key in (curses.KEY_UP, ord("k")):
                jump_num_list = []
                choice_index = (choice_index - 1) % len(options)
            elif key in (curses.KEY_DOWN, ord("j")):
                jump_num_list = []
                choice_index = (choice_index + 1) % len(options)
            elif key in (ord(digit) for digit in "1234567890"):
                if len(jump_num_list) < 6:
                    jump_num_list.append(chr(key))
            elif key in [curses.KEY_BACKSPACE, ord("\b"), ord("\x7f")]:
                if jump_num_list:
                    jump_num_list.pop()
            elif key == ord("g"):
                jump_num_list = []
                choice_index = 0
            elif key == ord("G"):
                jump_num_list = []
                choice_index = len(options) - 1
            elif key in (ord("q"), ord("h"), curses.KEY_LEFT):
                raise KeyboardInterrupt
            elif key in (curses.KEY_ENTER, 10, 13, ord("l"), curses.KEY_RIGHT):
                if jump_num_list:
                    jump_num = int("".join(jump_num_list))
                    choice_index = min(jump_num - 1, len(options) - 1)
                    jump_num_list = []
                elif query_style is ItemQuery:
                    return options[choice_index]
                elif query_style is IndexQuery:
                    return choice_index
                elif query_style is CombinedQuery:
                    return options[choice_index], choice_index
                else:
                    raise UnknownQueryStyle


def notify(message):
    """Notify the user until they confirm having seen it."""
    select_query(message, ["ok"], show_item_number=False)


def user_input(query, max_input_length=40):
    """Get a string of written input from the user."""
    return curses.wrapper(_user_input_ncurses, query, max_input_length=max_input_length)


def _user_input_ncurses(stdscr, query, max_input_length=40):
    """Ncurses level of do_get_user_input, it should never be called directly
    but always through do_get_user_input.
    """
    curses.curs_set(0)
    curses.init_pair(CONFIG.HIGHLIGHTED, curses.COLOR_BLACK, curses.COLOR_WHITE)
    curses.init_pair(CONFIG.NOT_HIGHLIGHTED, curses.COLOR_WHITE, curses.COLOR_BLACK)
    curses.curs_set(0)
    cursor_position = 0
    user_input_chars = []
    while True:
        print_menu(
            query,
            [
                "".join(user_input_chars),
                "".join(
                    "—" if i == cursor_position else " "
                    for i in range(max_input_length)
                ),
            ],
            stdscr,
            0,
            x_alignment=max_input_length // 2,
            show_item_number=False,
        )
        key = stdscr.getch()
        if key in (curses.KEY_BACKSPACE, ord("\b"), ord("\x7f")):
            delete_index = cursor_position - 1
            if delete_index >= 0:
                user_input_chars.pop(cursor_position - 1)
            cursor_position = max(0, cursor_position - 1)
        elif key in (curses.KEY_DC,):
            delete_index = cursor_position + 1
            if delete_index <= len(user_input_chars):
                user_input_chars.pop(cursor_position)
        elif key in (curses.KEY_ENTER, 10, 13):
            return "".join(user_input_chars)
        elif key == curses.KEY_LEFT:
            cursor_position = max(0, cursor_position - 1)
        elif key == curses.KEY_RIGHT:
            cursor_position = min(len(user_input_chars), cursor_position + 1)
        elif key == curses.KEY_RESIZE:
            pass
        elif len(user_input_chars) < max_input_length:
            user_input_chars.insert(cursor_position, chr(key))
            cursor_position = min(max_input_length, cursor_position + 1)


def print_menu(
    query,
    menu,
    stdscr,
    choice_index,
    x_alignment=None,
    show_item_number=True,
    jump_num_str="",
    canvas=None,
):
    """Visually represent a query and a number of menu items to the user, by
    using nCurses. It is used for all text printing in the program (even where
    no application level menu is presented, i.e. by simply not providing a query
    and no menu objects).
    """
    if canvas is None:
        canvas = NoCanvas()
    stdscr.clear()
    height, width = stdscr.getmaxyx()
    screen_center_x = width // 2
    screen_center_y = height // 2
    n_rows_to_print = len(menu) + 2

    if x_alignment is not None:
        item_x = max(min(screen_center_x - x_alignment, width - 2), 0)
    elif menu:
        menu_width = max(
            len(f"{i+1}: {item}" if show_item_number else str(item))
            for i, item in enumerate(menu)
        )
        item_x = max(screen_center_x - menu_width // 2, 0)
    else:
        item_x = None

    if item_x != 0 and item_x is not None:
        item_x = max(min(item_x, width - 2), 0)

    jump_num_str = jump_num_str[: max(min(len(jump_num_str), width - 1), 0)]
    if jump_num_str:
        stdscr.addstr(0, 0, jump_num_str)

    offset = 0
    title_y = screen_center_y - n_rows_to_print // 2
    if n_rows_to_print >= height - 2:
        y_title_theoretical = screen_center_y - n_rows_to_print // 2
        y_selected_theoretical = y_title_theoretical + 2 + choice_index
        y_last_theoretical = y_title_theoretical + n_rows_to_print - 1
        offset = min(
            max(y_selected_theoretical - screen_center_y, y_title_theoretical),
            y_last_theoretical - (height - 2),
        )
    title_y -= offset

    title_x = max(screen_center_x - (len(query) // 2), 0)
    if title_x != 0:
        title_x = max(min(abs(title_x), width) * (title_x // abs(title_x)), 0)
    if len(query) >= width - 1:
        query = query[0 : width - 1]
    if 0 <= title_y < height - 1:
        stdscr.addstr(title_y, title_x, query)
    for i, item in enumerate(menu):
        item_string = f"{i+1}: {item}" if show_item_number else str(item)
        if item_x + len(item_string) >= width - 1:
            item_string = item_string[: max((width - item_x - 2), 0)]
        attr = curses.color_pair(
            CONFIG.HIGHLIGHTED if i == choice_index else CONFIG.NOT_HIGHLIGHTED
        )
        if (
            i == choice_index
            and hasattr(item, "description")
            and hasattr(item.description, "getThumbnail")
            and type(canvas) is not NoCanvas
        ):
            thumbnail_width = item_x - 1
            thumbnail_height = height - 3
            if not (thumbnail_width <= 0 or thumbnail_height <= 0):
                thumbnail_placement = canvas.create_placement(
                    "thumbnail",
                    x=0,
                    y=2,
                    scaler=ueberzug.ScalerOption.CONTAIN.value,
                    width=thumbnail_width,
                    height=thumbnail_height,
                )
                thumbnail_placement.path = item.description.get_thumbnail()
                thumbnail_placement.visibility = ueberzug.Visibility.VISIBLE
        stdscr.attron(attr)
        item_y = screen_center_y - n_rows_to_print // 2 + i + 2 - offset
        if 0 <= item_y < height - 1 and item_string:
            stdscr.addstr(item_y, item_x, item_string)
        stdscr.attroff(attr)
