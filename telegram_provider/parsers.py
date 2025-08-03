import argparse
from ctypes import ArgumentError


class Formatter(argparse.HelpFormatter):
    def __init__(self, *args, indent_increment=1, width=70, **kwargs):
        super().__init__(
            *args,
            indent_increment=indent_increment,
            width=width,
            **kwargs,
        )

    def _format_action_invocation(self, action):
        # Copied exactly from argparse.ArgumentParser._format_action_invocation,
        # except marked "overridden"
        if not action.option_strings:
            default = self._get_default_metavar_for_positional(action)
            (metavar,) = self._metavar_formatter(action, default)(1)
            return f"<code>{metavar}</code>"  # Overridden

        else:
            parts = []

            # if the Optional doesn't take a value, format is:
            #    -s, --long
            if action.nargs == 0:
                parts.extend(
                    [f"<code>{i}</code>" for i in action.option_strings]
                )  # Overridden

            # if the Optional takes a value, format is:
            #    -s ARGS, --long ARGS
            else:
                default = self._get_default_metavar_for_optional(action)
                args_string = self._format_args(action, default)
                for option_string in action.option_strings:
                    parts.append(
                        "<code>%s %s</code>" % (option_string, args_string)
                    )  # Overridden

            return ", ".join(parts)

    # use defined argument order to display usage
    # Source: https://stackoverflow.com/questions/26985650/argparse-do-not-catch-positional-arguments-with-nargs/26986546#26986546
    def _format_usage(self, usage, actions, groups, prefix):
        if prefix is None:
            prefix = "usage: <code>"

        # if usage is specified, use that
        if usage is not None:
            usage = usage % dict(prog=self._prog)

        # if no optionals or positionals are available, usage is just prog
        elif usage is None and not actions:
            usage = "%(prog)s" % dict(prog=self._prog)
        elif usage is None:
            prog = "<code>%(prog)s</code>" % dict(prog=self._prog)
            # build full usage string
            action_usage = self._format_actions_usage(actions, groups)  # NEW
            usage = " ".join([s for s in [prog, action_usage] if s])
            # omit the long line wrapping code
        # prefix with 'usage:'
        return "%s</code>%s\n\n" % (prefix, usage)


class ArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise ArgumentError(message)


def spotting_parser():
    parser = ArgumentParser(
        prog="/spot",
        description="Input TranSPOT spotting entry.",
        formatter_class=Formatter,
        add_help=False,
    )

    parser.add_argument(
        "vehicle_number",
        help="Vehicle number, currently only supports exact set number",
    )

    parser.add_argument("--anon", action="store_true", help="Anonymous Entry")

    parser.add_argument(
        "-w",
        "--wheel-status",
        type=int,
        help="Wheel status (1-5): 1: Fresh, 2: Near perfect, 3: Flat, 4: Worn out, 5: Worrying",
        choices=[1, 2, 3, 4, 5],
    )

    parser.add_argument(
        "-s",
        "--status",
        type=int,
        help="Vehicle status (1-4): 1: In Service (default), 2: Not in Service, 3: Decommissioned, 4: Testing",
        default=1,
        choices=[1, 2, 3, 4],
    )

    parser.add_argument(
        "-r",
        "--run-number",
        type=str,
        help="Run number",
    )

    # parser.add_argument(
    #     "-l",
    #     "--loc",
    #     "--location",
    #     help=(
    #         "[Beta] "
    #         "Location properties. "
    #         "You may do station-station by code ('KG05-KG12'), "
    #         "or by name ('Phileo-KL_Sentral'), take note of using underscores as space seperator, "
    #         "and that it searches based on significant character strategy."
    #     ),
    # )

    parser.add_argument(
        "-n",
        "--notes",
        nargs="+",
        help="Notes to add to the notes field.",
        default="",
    )

    # parser.add_argument("filename")  # positional argument
    # parser.add_argument("-c", "--count")  # option that takes a value
    # parser.add_argument("-v", "--verbose", action="store_true")  # on/off flag
    # parser.add_argument(
    #     "integers",
    #     metavar="N",
    #     type=int,
    #     nargs="+",
    #     help="an integer for the accumulator",
    # )
    # parser.add_argument(
    #     "--sum",
    #     dest="accumulate",
    #     action="store_const",
    #     const=sum,
    #     default=max,
    #     help="sum the integers (default: find the max)",
    # )

    return parser
