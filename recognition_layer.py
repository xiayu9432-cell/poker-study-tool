import cv2
import numpy as np


class RecognitionLayer:
    @staticmethod
    def scale_box(box, width, height, reference=(888, 1920)):
        reference_width, reference_height = reference
        scale = min(width / reference_width, height / reference_height)
        offset_x = round((width - reference_width * scale) / 2)
        offset_y = round((height - reference_height * scale) / 2)
        x1, y1, x2, y2 = box
        return (offset_x + round(x1 * scale), offset_y + round(y1 * scale),
                offset_x + round(x2 * scale), offset_y + round(y2 * scale))

    @staticmethod
    def detect_special_scene(frame):
        height, width = frame.shape[:2]
        if height < 200 or width < 150:
            return None
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        saturation, value = hsv[:, :, 1], hsv[:, :, 2]
        table_green = ((hsv[:, :, 0] >= 35) & (hsv[:, :, 0] <= 90) &
                       (saturation >= 45) & (value >= 55))
        dark_panel = hsv[int(height * .15):int(height * .87), int(width * .06):int(width * .95)]
        profile_panel = value[int(height * .25):int(height * .74), int(width * .05):int(width * .95)]
        profile_footer = value[int(height * .80):int(height * .88), int(width * .07):int(width * .93)]
        outer = np.ones((height, width), dtype=bool)
        outer[int(height * .20):int(height * .78), int(width * .04):int(width * .96)] = False
        if (float(np.mean(profile_panel < 75)) >= .72 and
                float(np.mean(profile_footer < 75)) < .55 and
                float(np.mean(table_green[outer])) >= .45):
            return "player_profile"
        cyan = cv2.inRange(hsv, np.array([75, 75, 80]), np.array([105, 255, 255]))
        blue = cv2.inRange(hsv, np.array([85, 55, 75]), np.array([120, 255, 255]))
        runout = blue[int(height * .32):int(height * .65), int(width * .05):int(width * .95)]
        center_region = hsv[int(height * .35):int(height * .62), int(width * .08):int(width * .92)]
        if float(np.mean(runout > 0)) >= .42 and float(np.mean(center_region[:, :, 1] > 40)) >= .68:
            return "allin_runout"
        cyan_bottom = float(np.mean(cyan[int(height * .76):int(height * .86), int(width * .48):int(width * .82)] > 0))
        if float(np.mean(dark_panel[:, :, 2] < 70)) >= .55 and .08 <= cyan_bottom <= .40:
            return "insurance"
        insurance_panel = value[int(height * .59):int(height * .66), int(width * .30):int(width * .70)]
        cyan_notice = float(np.mean(cyan[:int(height * .11)] > 0))
        dark_insurance_panel = float(np.mean(insurance_panel < 75))
        if cyan_notice >= .012 and dark_insurance_panel >= .53:
            return "insurance"
        left_panel = value[int(height * .08):int(height * .92), :int(width * .37)]
        right_table = table_green[int(height * .08):int(height * .92), int(width * .40):]
        if float(np.mean(left_panel < 75)) >= .48 and float(np.mean(right_table)) >= .30:
            return "table_menu"
        board_band = hsv[int(height * .34):int(height * .62), int(width * .15):int(width * .85)]
        backs = (((board_band[:, :, 0] <= 12) | (board_band[:, :, 0] >= 165)) &
                 (board_band[:, :, 1] >= 80) & (board_band[:, :, 2] >= 65)).astype(np.uint8) * 255
        backs = cv2.morphologyEx(backs, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)))
        contours, _ = cv2.findContours(backs, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            _, _, box_width, box_height = cv2.boundingRect(contour)
            ratio = box_width / max(box_height, 1)
            fill = cv2.contourArea(contour) / max(box_width * box_height, 1)
            if (height * .055 <= box_height <= height * .11 and width * .05 <= box_width <= width * .14
                    and .55 <= ratio <= .85 and fill >= .80):
                return "community_card_deal"
        center = hsv[int(height * .10):int(height * .92), int(width * .05):int(width * .95)]
        if float(np.mean(center[:, :, 2] < 65)) >= .72 and float(np.mean(center[:, :, 1] < 55)) >= .62:
            return "resource_loading"
        if (float(np.mean(value > 180)) >= .70 and float(np.mean(saturation < 55)) >= .62
                and float(np.mean(table_green)) < .08):
            return "lobby"
        border = np.zeros((height, width), dtype=bool)
        border[:int(height * .08)] = True; border[int(height * .92):] = True
        border[:, :int(width * .08)] = True; border[:, int(width * .92):] = True
        glow = ((hsv[:, :, 0] >= 18) & (hsv[:, :, 0] <= 45) &
                (hsv[:, :, 1] > 80) & (hsv[:, :, 2] > 140))
        overlay_border = (np.any(np.mean(glow, axis=1) >= .80) or
                          np.any(np.mean(glow, axis=0) >= .80))
        if not overlay_border and float(np.mean(glow[border])) >= .015:
            return "lucky_impact"
        contours, _ = cv2.findContours(blue, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            x, y, box_width, box_height = cv2.boundingRect(contour)
            if box_width >= width * .55 and box_height >= height * .14 and x <= width * .25 and height * .32 <= y <= height * .65:
                return "allin_runout"
        return None
    @staticmethod
    def count_card_boxes(image):
        if image.size == 0:
            return 0
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        mask = cv2.inRange(gray, 150, 255)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        boxes = 0
        for contour in contours:
            _, _, width, height = cv2.boundingRect(contour)
            ratio = width / max(height, 1)
            if height >= image.shape[0] * .22 and .48 <= ratio <= .82:
                boxes += 1
        return min(5, boxes)

    @staticmethod
    def card_suit(card):
        height, width = card.shape[:2]
        inner = card[int(height * .42):max(int(height * .43) + 1, int(height * .92)),
                     int(width * .15):max(int(width * .16) + 1, int(width * .85))]
        hsv = cv2.cvtColor(inner, cv2.COLOR_BGR2HSV)
        saturated = hsv[:, :, 1] > 80
        hue = hsv[:, :, 0][saturated]
        saturation_ratio = float(np.count_nonzero(saturated)) / max(saturated.size, 1)
        value = cv2.cvtColor(card, cv2.COLOR_BGR2HSV)[:, :, 2]
        bright_ratio = np.count_nonzero(value > 170) / max(value.size, 1)
        if not hue.size or saturation_ratio < .025:
            return "s" if bright_ratio >= .35 else None
        green = np.count_nonzero((hue >= 35) & (hue <= 90))
        blue = np.count_nonzero((hue > 90) & (hue <= 135))
        red = np.count_nonzero((hue < 12) | (hue > 165))
        dominant = max(green, blue, red) / max(saturated.size, 1)
        if dominant < .08:
            return "s"
        return "c" if green == max(green, blue, red) else "d" if blue == max(green, blue, red) else "h"

    @staticmethod
    def rank_distances(card, rank_templates):
        height, width = card.shape[:2]
        crop = card[:max(1, int(height * .42)), :max(1, int(width * .48))]
        glyph = cv2.resize(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), (24, 32),
                           interpolation=cv2.INTER_AREA)
        glyph = cv2.threshold(glyph, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
        glyph = glyph.flatten().astype(float)
        distances = []
        for rank, value in rank_templates.items():
            for raw_template in value.get("templates", [value.get("template", [])]):
                template = np.asarray(raw_template, dtype=float)
                if template.size == glyph.size:
                    distances.append((float(np.mean(np.abs(glyph - template))), rank))
        return sorted(distances)
