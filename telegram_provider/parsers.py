import argparse
from ctypes import ArgumentError


class Formatter(argparse.HelpFormatter):
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
    )

    parser.add_argument(
        "-s",
        "--status",
        type=int,
        help="Vehicle status (1-4): 1: In Service (default), 2: Not in Service, 3: Decommissioned, 4: Testing",
        default=1,
    )

    parser.add_argument(
        "-r",
        "--run-number",
        type=int,
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
