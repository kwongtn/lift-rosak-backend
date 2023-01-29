class SpinnerFrame:
    candidates = ["-", "\\", "|", "/"]
    current_index = -1

    def get_spinner_frame(self):
        self.current_index += 1

        return self.candidates[self.current_index % len(self.candidates)] + "  "
