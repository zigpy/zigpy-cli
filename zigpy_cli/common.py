import click


class HexOrDecIntParamType(click.ParamType):
    name = "integer"

    def convert(self, value, param, ctx):
        if isinstance(value, int):
            return value

        try:
            if value[:2].lower() == "0x":
                return int(value[2:], 16)
            else:
                return int(value, 10)
        except ValueError:
            self.fail(f"{value!r} is not a valid integer", param, ctx)


HEX_OR_DEC_INT = HexOrDecIntParamType()
