import json
from pathlib import Path
import tkinter as tk
from tkinter import messagebox

from PIL import Image, ImageTk

# PFADE

BASE_DIR = Path(__file__).resolve().parent.parent

IMAGE_DIR = BASE_DIR / "data" / "annotations" / "images"

LABEL_DIR = BASE_DIR / "data" / "annotations" / "labels"


# KLASSEN

LABELS = {
    "1": "STATION_FIELD",
    "2": "LINE_FIELD",
    "3": "PLAN_NUMBER_FIELD",
}


LABEL_COLORS = {
    "STATION_FIELD": "red",
    "LINE_FIELD": "blue",
    "PLAN_NUMBER_FIELD": "green",
}


# ANNOTATION TOOL


class AnnotationTool:

    def __init__(self, root):

        self.root = root

        self.root.title("LayoutParserBVG Annotation Tool")

        self.root.geometry("1500x950")

        LABEL_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )

        # Bilder suchen

        self.image_files = sorted(
            [
                path
                for path in IMAGE_DIR.iterdir()
                if (
                    path.is_file()
                    and path.suffix.lower()
                    in {
                        ".png",
                        ".jpg",
                        ".jpeg",
                    }
                )
            ]
        )

        if not self.image_files:

            messagebox.showerror(
                "Fehler",
                "Keine Trainingsbilder gefunden.",
            )

            self.root.destroy()
            return

        # Status

        self.current_index = 0

        self.current_label = "STATION_FIELD"

        self.annotations = []

        self.original_image = None
        self.photo_image = None

        # Bounding Box

        self.start_x = None
        self.start_y = None

        self.current_rectangle = None

        self.drawing_box = False

        # Zoom und Position

        self.zoom = 1.0

        self.min_zoom = 0.05
        self.max_zoom = 8.0

        self.offset_x = 0
        self.offset_y = 0

        self.move_step = 120

        # Kopfzeile

        self.info_frame = tk.Frame(self.root)

        self.info_frame.pack(
            fill="x",
            padx=10,
            pady=5,
        )

        self.file_label = tk.Label(
            self.info_frame,
            text="",
            font=(
                "Arial",
                14,
                "bold",
            ),
        )

        self.file_label.pack(side="left")

        self.class_label = tk.Label(
            self.info_frame,
            text="",
            font=(
                "Arial",
                14,
                "bold",
            ),
        )

        self.class_label.pack(side="right")

        # BUTTONS

        self.control_frame = tk.Frame(self.root)

        self.control_frame.pack(
            fill="x",
            padx=10,
            pady=5,
        )

        # Zoom
        tk.Button(
            self.control_frame,
            text="+ Zoom",
            width=10,
            command=self.zoom_in,
        ).pack(
            side="left",
            padx=5,
        )

        tk.Button(
            self.control_frame,
            text="- Zoom",
            width=10,
            command=self.zoom_out,
        ).pack(
            side="left",
            padx=5,
        )

        tk.Button(
            self.control_frame,
            text="Reset",
            width=10,
            command=self.reset_view,
        ).pack(
            side="left",
            padx=5,
        )

        # Abstand
        tk.Label(self.control_frame, text="     Bild verschieben: ").pack(side="left")

        tk.Button(
            self.control_frame,
            text="←",
            width=4,
            command=self.move_left,
        ).pack(
            side="left",
            padx=2,
        )

        tk.Button(
            self.control_frame,
            text="↑",
            width=4,
            command=self.move_up,
        ).pack(
            side="left",
            padx=2,
        )

        tk.Button(
            self.control_frame,
            text="↓",
            width=4,
            command=self.move_down,
        ).pack(
            side="left",
            padx=2,
        )

        tk.Button(
            self.control_frame,
            text="→",
            width=4,
            command=self.move_right,
        ).pack(
            side="left",
            padx=2,
        )

        # Hilfe

        help_text = (
            "Normal ziehen = Bounding Box    |    "
            "1 = STATION_FIELD    "
            "2 = LINE_FIELD    "
            "3 = PLAN_NUMBER_FIELD    |    "
            "S = Speichern    "
            "N = Nächstes Bild    "
            "P = Vorheriges Bild    "
            "U = Letzte Box löschen"
        )

        self.help_label = tk.Label(
            self.root,
            text=help_text,
            font=(
                "Arial",
                11,
            ),
        )

        self.help_label.pack(pady=5)

        # Canvas

        self.canvas = tk.Canvas(
            self.root,
            bg="gray20",
            highlightthickness=0,
        )

        self.canvas.pack(
            padx=10,
            pady=10,
            expand=True,
            fill="both",
        )

        # Bounding Box zeichnen

        self.canvas.bind(
            "<ButtonPress-1>",
            self.on_mouse_down,
        )

        self.canvas.bind(
            "<B1-Motion>",
            self.on_mouse_drag,
        )

        self.canvas.bind(
            "<ButtonRelease-1>",
            self.on_mouse_up,
        )

        # Tastatur

        self.root.bind(
            "1",
            lambda event: self.set_label("STATION_FIELD"),
        )

        self.root.bind(
            "2",
            lambda event: self.set_label("LINE_FIELD"),
        )

        self.root.bind(
            "3",
            lambda event: self.set_label("PLAN_NUMBER_FIELD"),
        )

        self.root.bind(
            "s",
            lambda event: self.save_annotations(),
        )

        self.root.bind(
            "S",
            lambda event: self.save_annotations(),
        )

        self.root.bind(
            "n",
            lambda event: self.next_image(),
        )

        self.root.bind(
            "N",
            lambda event: self.next_image(),
        )

        self.root.bind(
            "p",
            lambda event: self.previous_image(),
        )

        self.root.bind(
            "P",
            lambda event: self.previous_image(),
        )

        self.root.bind(
            "u",
            lambda event: self.undo_last_box(),
        )

        self.root.bind(
            "U",
            lambda event: self.undo_last_box(),
        )

        # Erstes Bild

        self.root.update_idletasks()

        self.load_image()

    # LABEL

    def set_label(
        self,
        label,
    ):

        self.current_label = label

        self.update_status()

    # BILD LADEN

    def load_image(self):

        file_path = self.image_files[self.current_index]

        self.original_image = Image.open(file_path).convert("RGB")

        self.load_existing_annotations()

        self.reset_view()

        self.update_status()

    # RESET

    def reset_view(self):

        self.root.update_idletasks()

        canvas_width = max(
            self.canvas.winfo_width(),
            100,
        )

        canvas_height = max(
            self.canvas.winfo_height(),
            100,
        )

        scale_x = canvas_width / self.original_image.width

        scale_y = canvas_height / self.original_image.height

        self.zoom = min(
            scale_x,
            scale_y,
        )

        self.zoom = max(
            self.min_zoom,
            self.zoom,
        )

        display_width = self.original_image.width * self.zoom

        display_height = self.original_image.height * self.zoom

        self.offset_x = (canvas_width - display_width) / 2

        self.offset_y = (canvas_height - display_height) / 2

        self.redraw()

        self.update_status()

    # ZOOM

    def zoom_in(self):

        self.zoom_center(1.25)

    def zoom_out(self):

        self.zoom_center(1 / 1.25)

    def zoom_center(
        self,
        factor,
    ):

        canvas_width = self.canvas.winfo_width()

        canvas_height = self.canvas.winfo_height()

        center_x = canvas_width / 2

        center_y = canvas_height / 2

        old_zoom = self.zoom

        new_zoom = old_zoom * factor

        new_zoom = max(
            self.min_zoom,
            min(
                self.max_zoom,
                new_zoom,
            ),
        )

        if abs(new_zoom - old_zoom) < 0.000001:
            return

        image_x = (center_x - self.offset_x) / old_zoom

        image_y = (center_y - self.offset_y) / old_zoom

        self.zoom = new_zoom

        self.offset_x = center_x - image_x * new_zoom

        self.offset_y = center_y - image_y * new_zoom

        self.redraw()

        self.update_status()

    # BILD VERSCHIEBEN

    def move_left(self):

        self.offset_x -= self.move_step

        self.redraw()

    def move_right(self):

        self.offset_x += self.move_step

        self.redraw()

    def move_up(self):

        self.offset_y -= self.move_step

        self.redraw()

    def move_down(self):

        self.offset_y += self.move_step

        self.redraw()

    # STATUS

    def update_status(self):

        file_path = self.image_files[self.current_index]

        self.file_label.config(
            text=(
                f"{self.current_index + 1}"
                f"/{len(self.image_files)}"
                f"   {file_path.name}"
                f"   | Zoom: "
                f"{self.zoom:.2f}x"
            )
        )

        self.class_label.config(
            text=("Aktuelle Klasse: " f"{self.current_label}"),
            fg=LABEL_COLORS[self.current_label],
        )

    # KOORDINATEN

    def canvas_to_image(
        self,
        x,
        y,
    ):

        image_x = (x - self.offset_x) / self.zoom

        image_y = (y - self.offset_y) / self.zoom

        return (
            image_x,
            image_y,
        )

    def image_to_canvas(
        self,
        x,
        y,
    ):

        canvas_x = x * self.zoom + self.offset_x

        canvas_y = y * self.zoom + self.offset_y

        return (
            canvas_x,
            canvas_y,
        )

    # BOX ZEICHNEN

    def on_mouse_down(
        self,
        event,
    ):

        self.drawing_box = True

        self.start_x = event.x

        self.start_y = event.y

        color = LABEL_COLORS[self.current_label]

        self.current_rectangle = self.canvas.create_rectangle(
            self.start_x,
            self.start_y,
            self.start_x,
            self.start_y,
            outline=color,
            width=3,
        )

    def on_mouse_drag(
        self,
        event,
    ):

        if not self.drawing_box or self.current_rectangle is None:
            return

        self.canvas.coords(
            self.current_rectangle,
            self.start_x,
            self.start_y,
            event.x,
            event.y,
        )

    def on_mouse_up(
        self,
        event,
    ):

        if not self.drawing_box or self.current_rectangle is None:
            return

        self.drawing_box = False

        end_x = event.x
        end_y = event.y

        x1 = min(
            self.start_x,
            end_x,
        )

        y1 = min(
            self.start_y,
            end_y,
        )

        x2 = max(
            self.start_x,
            end_x,
        )

        y2 = max(
            self.start_y,
            end_y,
        )

        if x2 - x1 < 5 or y2 - y1 < 5:

            self.canvas.delete(self.current_rectangle)

            self.current_rectangle = None

            return

        image_x1, image_y1 = self.canvas_to_image(
            x1,
            y1,
        )

        image_x2, image_y2 = self.canvas_to_image(
            x2,
            y2,
        )

        image_x1 = max(
            0,
            min(
                self.original_image.width,
                image_x1,
            ),
        )

        image_y1 = max(
            0,
            min(
                self.original_image.height,
                image_y1,
            ),
        )

        image_x2 = max(
            0,
            min(
                self.original_image.width,
                image_x2,
            ),
        )

        image_y2 = max(
            0,
            min(
                self.original_image.height,
                image_y2,
            ),
        )

        if image_x2 <= image_x1 or image_y2 <= image_y1:

            self.current_rectangle = None

            self.redraw()

            return

        annotation = {
            "label": self.current_label,
            "bbox": [
                int(image_x1),
                int(image_y1),
                int(image_x2),
                int(image_y2),
            ],
        }

        self.annotations.append(annotation)

        self.current_rectangle = None

        self.redraw()

    # ANZEIGE

    def redraw(self):

        self.canvas.delete("all")

        display_width = max(
            1,
            int(self.original_image.width * self.zoom),
        )

        display_height = max(
            1,
            int(self.original_image.height * self.zoom),
        )

        display_image = self.original_image.resize(
            (
                display_width,
                display_height,
            ),
            Image.Resampling.LANCZOS,
        )

        self.photo_image = ImageTk.PhotoImage(display_image)

        self.canvas.create_image(
            self.offset_x,
            self.offset_y,
            anchor="nw",
            image=self.photo_image,
        )

        self.draw_annotations()

    # ANNOTATIONEN ZEICHNEN

    def draw_annotations(self):

        for annotation in self.annotations:

            label = annotation["label"]

            bbox = annotation["bbox"]

            x1, y1 = self.image_to_canvas(
                bbox[0],
                bbox[1],
            )

            x2, y2 = self.image_to_canvas(
                bbox[2],
                bbox[3],
            )

            color = LABEL_COLORS.get(
                label,
                "yellow",
            )

            self.canvas.create_rectangle(
                x1,
                y1,
                x2,
                y2,
                outline=color,
                width=3,
            )

            self.canvas.create_text(
                x1 + 5,
                y1 + 5,
                anchor="nw",
                text=label,
                fill=color,
                font=(
                    "Arial",
                    12,
                    "bold",
                ),
            )

    # SPEICHERN

    def save_annotations(self):

        file_path = self.image_files[self.current_index]

        label_path = LABEL_DIR / (file_path.stem + ".json")

        data = {
            "image": file_path.name,
            "width": self.original_image.width,
            "height": self.original_image.height,
            "annotations": self.annotations,
        }

        with open(
            label_path,
            "w",
            encoding="utf-8",
        ) as output_file:

            json.dump(
                data,
                output_file,
                indent=4,
                ensure_ascii=False,
            )

        print(f"Gespeichert: " f"{label_path.name}")

    # VORHANDENE ANNOTATIONEN LADEN

    def load_existing_annotations(self):

        file_path = self.image_files[self.current_index]

        label_path = LABEL_DIR / (file_path.stem + ".json")

        if not label_path.exists():

            self.annotations = []

            return

        with open(
            label_path,
            "r",
            encoding="utf-8",
        ) as input_file:

            data = json.load(input_file)

        self.annotations = data.get(
            "annotations",
            [],
        )

    # LETZTE BOX LÖSCHEN

    def undo_last_box(self):

        if not self.annotations:

            print("Keine Annotation zum Löschen.")

            return

        removed = self.annotations.pop()

        print("Annotation gelöscht: " f"{removed['label']}")

        self.redraw()

    # NÄCHSTES BILD

    def next_image(self):

        self.save_annotations()

        if self.current_index < len(self.image_files) - 1:

            self.current_index += 1

            self.load_image()

        else:

            messagebox.showinfo(
                "Fertig",
                "Du bist beim letzten Bild angekommen.",
            )

    # VORHERIGES BILD

    def previous_image(self):

        self.save_annotations()

        if self.current_index > 0:

            self.current_index -= 1

            self.load_image()

        else:

            messagebox.showinfo(
                "Hinweis",
                "Du bist bereits beim ersten Bild.",
            )


# START


def main():

    root = tk.Tk()

    AnnotationTool(root)

    root.mainloop()


if __name__ == "__main__":
    main()
