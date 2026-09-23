import math
import json
import random
import socket
import sys
import time
from pathlib import Path
from array import array

import pygame


SCREEN_WIDTH = 960
SCREEN_HEIGHT = 540
FPS = 60
FOCAL_LENGTH = 560
HORIZON = 220
WORLD_END = 116
LOBBY_BUTTON_Z = 24
PROFILE_FILE = "player_profile.json"
WORLD_THEME_FILE = "mario theme.ogg"
FLOOR_TEXTURE_FILE = "floor.jpg"
COIN_TEXTURE_FILE = "coin.png"
COIN_SOUND_FILE = "coin.wav"
JUMP_SOUND_FILE = "jump.wav"
DIE_SOUND_FILE = "die.wav"
KILL_SOUND_FILE = "kill.wav"

SKY = (92, 180, 235)
INK = (25, 31, 52)
WHITE = (255, 255, 255)
RED = (216, 45, 48)
BLUE = (48, 78, 177)
GOLD = (255, 211, 48)
GRASS = (66, 176, 78)
DIRT = (143, 81, 46)

MARIO_MODEL_DIR = Path(__file__).resolve().parent / "assets" / "mario_rig_64"
GOOMBA_TEXTURE_FILE = Path(__file__).resolve().parent / "assets" / "goomba" / "goomba_texture.png"
GOOMBA_ANIMATION_FILE = Path(__file__).resolve().parent / "assets" / "goomba" / "goomba_animation.json"
MARIO_MATERIAL_COLORS = ((48, 78, 177), (216, 45, 48), WHITE, (245, 244, 232),
                         (247, 190, 140), (101, 56, 31), (216, 45, 48))


def apply_static_mario_pose(name, source_positions, indices):
    """Bend the source T-pose arms down once, without playing an animation."""
    positions = [list(vertex) for vertex in source_positions]
    mesh_name = name.lower()
    if "mario64hand" in mesh_name:
        side = 1 if sum(vertex[0] for vertex in positions) >= 0 else -1
        arm_groups = (range(len(positions)),)
    elif mesh_name == "mario__bodymt":
        parents = list(range(len(positions)))

        def find_root(vertex_index):
            while parents[vertex_index] != vertex_index:
                parents[vertex_index] = parents[parents[vertex_index]]
                vertex_index = parents[vertex_index]
            return vertex_index

        for index in range(0, len(indices) - 2, 3):
            first, second, third = indices[index:index + 3]
            first_root, second_root, third_root = (find_root(first), find_root(second),
                                                   find_root(third))
            parents[second_root] = first_root
            parents[third_root] = first_root
        components = {}
        for vertex_index in set(indices):
            components.setdefault(find_root(vertex_index), []).append(vertex_index)
        arm_groups = []
        for component in components.values():
            component_vertices = [positions[index] for index in component]
            center_x = sum(vertex[0] for vertex in component_vertices) / len(component_vertices)
            min_y = min(vertex[1] for vertex in component_vertices)
            if min_y > 1.65 and abs(center_x) > 0.2:
                arm_groups.append(component)
    else:
        return positions

    for group in arm_groups:
        if "mario64hand" not in mesh_name:
            center_x = sum(positions[index][0] for index in group) / len(group)
            side = 1 if center_x > 0 else -1
        pivot_x, pivot_y = side * 0.4, 1.9
        angle = math.radians(-60 * side)
        cosine, sine = math.cos(angle), math.sin(angle)
        for vertex_index in group:
            x, y, _ = positions[vertex_index]
            offset_x, offset_y = x - pivot_x, y - pivot_y
            positions[vertex_index][0] = pivot_x + offset_x * cosine - offset_y * sine
            positions[vertex_index][1] = pivot_y + offset_x * sine + offset_y * cosine
    return positions


def load_mario_meshes():
    """Load the new Mario 64 mesh in a static bind pose for the lightweight renderer."""
    try:
        model = json.loads((MARIO_MODEL_DIR / "mario_static.json").read_text(encoding="utf-8"))
        materials = [MARIO_MODEL_DIR / material["texture"] if material.get("texture") else None
                     for material in model["materials"]]
        meshes = []
        hand_meshes = []
        for part in model["parts"]:
            material = part["material"]
            base_color = MARIO_MATERIAL_COLORS[material % len(MARIO_MATERIAL_COLORS)]
            positions = apply_static_mario_pose(part.get("name", ""),
                                                part["positions"], part["indices"])
            mesh = (positions, part["indices"], base_color,
                    part["uvs"], material)
            meshes.append(mesh)
            if "mario64hand" in part.get("name", "").lower():
                hand_meshes.append(mesh)
        return meshes, materials, hand_meshes
    except (OSError, KeyError, ValueError, IndexError, TypeError):
        return [], [], []


MARIO_MESHES, MARIO_MATERIAL_FILES, MARIO_HAND_MESHES = load_mario_meshes()


def load_goomba_animation():
    try:
        data = json.loads(GOOMBA_ANIMATION_FILE.read_text(encoding="utf-8"))
        if data.get("frames") and data.get("indices") and data.get("uvs"):
            return data
    except (OSError, ValueError, TypeError):
        pass
    return None


GOOMBA_ANIMATION = load_goomba_animation()


def make_textures(character_style=0):
    textures = {}
    textures["mario_materials"] = []
    for texture_path in MARIO_MATERIAL_FILES:
        try:
            textures["mario_materials"].append(
                pygame.image.load(str(texture_path)).convert_alpha() if texture_path else None)
        except (pygame.error, OSError):
            textures["mario_materials"].append(None)
    grass = pygame.Surface((16, 16))
    grass.fill((67, 167, 72))
    for x, y in ((2, 3), (8, 5), (13, 2), (5, 12), (11, 10)):
        pygame.draw.rect(grass, (38, 123, 61), (x, y, 2, 3))
    # Use the supplied brick image for the large ground platform.  Keep the
    # generated grass available as a fallback if the image is unavailable.
    try:
        floor = pygame.image.load(FLOOR_TEXTURE_FILE).convert()
        textures["floor"] = floor
    except (pygame.error, OSError):
        textures["floor"] = grass
    textures["grass"] = grass

    brick = pygame.Surface((16, 16))
    brick.fill((157, 82, 48))
    pygame.draw.rect(brick, (205, 116, 59), (1, 1, 14, 6), 1)
    pygame.draw.rect(brick, (205, 116, 59), (1, 9, 14, 6), 1)
    pygame.draw.line(brick, (102, 54, 40), (8, 1), (8, 7), 1)
    pygame.draw.line(brick, (102, 54, 40), (4, 9), (4, 15), 1)
    textures["brick"] = brick

    mario = pygame.Surface((16, 16))
    mario.fill(RED)
    pygame.draw.rect(mario, BLUE, (3, 8, 10, 7))
    pygame.draw.rect(mario, (247, 190, 140), (5, 4, 6, 5))
    textures["mario"] = mario

    skin = pygame.Surface((16, 16))
    skin.fill((247, 190, 140))
    pygame.draw.rect(skin, (214, 143, 101), (1, 12, 14, 3))
    textures["skin"] = skin

    overalls = pygame.Surface((16, 16))
    overalls.fill((43, 75, 178))
    pygame.draw.rect(overalls, (87, 119, 227), (2, 2, 12, 3))
    pygame.draw.rect(overalls, GOLD, (4, 6, 2, 2))
    pygame.draw.rect(overalls, GOLD, (10, 6, 2, 2))
    textures["overalls"] = overalls

    style_colors = ((198, 32, 40), (40, 93, 198), (112, 52, 164))
    cap_color = style_colors[character_style % len(style_colors)]
    cap = pygame.Surface((16, 16))
    cap.fill(cap_color)
    textures["cap"] = cap

    shoe = pygame.Surface((16, 16))
    shoe.fill((103, 53, 37))
    pygame.draw.rect(shoe, (178, 94, 45), (2, 2, 12, 4))
    textures["shoe"] = shoe

    glove = pygame.Surface((16, 16))
    glove.fill((245, 244, 232))
    pygame.draw.rect(glove, (209, 214, 222), (1, 11, 14, 4))
    textures["glove"] = glove

    hair = pygame.Surface((16, 16))
    hair.fill((91, 46, 30))
    pygame.draw.rect(hair, (143, 76, 39), (2, 2, 12, 4))
    textures["hair"] = hair

    coin = pygame.Surface((16, 16))
    coin.fill((245, 182, 34))
    pygame.draw.rect(coin, (255, 239, 115), (3, 1, 10, 14), 2)
    pygame.draw.line(coin, (255, 250, 180), (6, 3), (6, 12), 2)
    textures["coin"] = coin
    try:
        coin_sprite = pygame.image.load(COIN_TEXTURE_FILE).convert_alpha()
        coin_bounds = coin_sprite.get_bounding_rect()
        textures["coin_sprite"] = coin_sprite.subsurface(coin_bounds).copy()
    except (pygame.error, OSError, ValueError):
        textures["coin_sprite"] = None
    textures["coin_sprite_cache"] = {}

    enemy = pygame.Surface((16, 16))
    enemy.fill((137, 76, 46))
    textures["enemy"] = enemy
    try:
        atlas = pygame.image.load(str(GOOMBA_TEXTURE_FILE)).convert_alpha()
        # Fallback 2D face crop from the supplied model's upper-left atlas region.
        face = atlas.subsurface((100, 100, 300, 300)).copy()
        face_mask = pygame.Surface(face.get_size(), pygame.SRCALPHA)
        pygame.draw.ellipse(face_mask, (255, 255, 255, 255), face_mask.get_rect())
        face.blit(face_mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        textures["enemy_face"] = face
    except (pygame.error, OSError, ValueError):
        textures["enemy_face"] = None
    try:
        textures["goomba_model"] = pygame.image.load(str(GOOMBA_TEXTURE_FILE)).convert_alpha()
    except (pygame.error, OSError, ValueError):
        textures["goomba_model"] = None

    shell = pygame.Surface((16, 16))
    shell.fill((47, 143, 82))
    pygame.draw.rect(shell, (31, 92, 65), (1, 1, 14, 14), 2)
    pygame.draw.line(shell, (108, 207, 111), (3, 12), (13, 3), 2)
    pygame.draw.line(shell, (108, 207, 111), (3, 5), (11, 14), 2)
    textures["shell"] = shell
    return textures


def make_mario_icon():
    icon = pygame.Surface((32, 32), pygame.SRCALPHA)
    icon.fill((25, 31, 52, 255))
    pygame.draw.rect(icon, (198, 32, 40), (5, 3, 22, 8))
    pygame.draw.rect(icon, (240, 65, 61), (3, 10, 26, 6))
    pygame.draw.rect(icon, (247, 190, 140), (7, 14, 18, 11))
    pygame.draw.rect(icon, (247, 190, 140), (4, 20, 24, 5))
    pygame.draw.rect(icon, (43, 75, 178), (7, 25, 18, 6))
    pygame.draw.rect(icon, INK, (10, 17, 3, 4))
    pygame.draw.rect(icon, INK, (19, 17, 3, 4))
    pygame.draw.rect(icon, INK, (12, 22, 9, 3))
    pygame.draw.circle(icon, WHITE, (16, 8), 3)
    pygame.draw.line(icon, RED, (16, 6), (16, 10), 1)
    return icon


def load_profile():
    try:
        with open(PROFILE_FILE, "r", encoding="utf-8") as profile_file:
            profile = json.load(profile_file)
        name = str(profile.get("name", "Mario"))[:16] or "Mario"
        style = int(profile.get("style", 0)) % 3
        return name, style
    except (OSError, ValueError, TypeError):
        return "Mario", 0


def save_profile(name, style):
    profile = {"name": name[:16] or "Mario", "style": int(style) % 3}
    try:
        with open(PROFILE_FILE, "w", encoding="utf-8") as profile_file:
            json.dump(profile, profile_file, indent=2)
        return True
    except OSError:
        return False


def texture_color(texture, depth, face_index):
    x = int(abs(depth) * 5 + face_index * 3) % texture.get_width()
    y = int(abs(depth) * 3 + face_index * 5) % texture.get_height()
    return texture.get_at((x, y))[:3]


def make_tone(frequency, duration, volume=0.25, end_frequency=None):
    sample_rate = 22050
    samples = array("h")
    total = int(sample_rate * duration)
    end_frequency = end_frequency or frequency
    for index in range(total):
        progress = index / max(total, 1)
        current_frequency = frequency + (end_frequency - frequency) * progress
        envelope = min(1, index / 250, (total - index) / 1000)
        value = int(32767 * volume * envelope * math.sin(2 * math.pi * current_frequency * index / sample_rate))
        samples.append(value)
    return pygame.mixer.Sound(buffer=samples.tobytes())


def make_music():
    notes = (262, 0, 330, 392, 0, 330, 294, 0, 349, 440, 0, 392, 330, 294, 262, 0)
    bass_notes = (131, 131, 165, 196, 147, 147, 175, 220, 165, 165, 196, 220, 131, 147, 165, 131)
    mixer_rate, _, mixer_channels = pygame.mixer.get_init() or (22050, -16, 1)
    samples = array("h")
    note_length = int(mixer_rate * 0.22)
    for note, bass in zip(notes, bass_notes):
        for index in range(note_length):
            envelope = min(1, index / 240, (note_length - index) / 900)
            melody = 0 if note == 0 else math.sin(2 * math.pi * note * index / mixer_rate)
            low = math.sin(2 * math.pi * bass * index / mixer_rate)
            value = int(32767 * envelope * (0.045 * melody + 0.018 * low))
            for _ in range(mixer_channels):
                samples.append(value)
    return pygame.mixer.Sound(buffer=samples.tobytes())


def setup_audio():
    try:
        pygame.mixer.init(frequency=22050, size=-16, channels=1, buffer=512)
        try:
            coin_sound = pygame.mixer.Sound(COIN_SOUND_FILE)
        except (pygame.error, OSError):
            coin_sound = make_tone(880, 0.1, end_frequency=1320)
        try:
            jump_sound = pygame.mixer.Sound(JUMP_SOUND_FILE)
        except (pygame.error, OSError):
            jump_sound = make_tone(440, 0.16, end_frequency=720)
        try:
            kill_sound = pygame.mixer.Sound(KILL_SOUND_FILE)
        except (pygame.error, OSError):
            kill_sound = make_tone(170, 0.14, end_frequency=90)
        try:
            die_sound = pygame.mixer.Sound(DIE_SOUND_FILE)
        except (pygame.error, OSError):
            die_sound = make_tone(180, 0.28, end_frequency=70)
        sounds = {
            "jump": jump_sound,
            "coin": coin_sound,
            "stomp": kill_sound,
            "hurt": die_sound,
        }
        try:
            pygame.mixer.music.load(WORLD_THEME_FILE)
            pygame.mixer.music.set_volume(0.28)
        except (pygame.error, OSError):
            pass
        return sounds
    except (pygame.error, OSError):
        return {}


def play_world_theme():
    """Start the main theme when the player enters a world."""
    try:
        pygame.mixer.music.play(-1)
    except pygame.error:
        pass


class NetworkSession:
    port = 50007

    def __init__(self, name, mode, address, port=None):
        self.name = name
        self.mode = mode
        self.port = int(port or NetworkSession.port)
        resolved_address = socket.gethostbyname(address) if mode == "join" else address
        self.address = (resolved_address, self.port)
        self.player_id = f"{name}-{random.randrange(100000, 999999)}"
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.setblocking(False)
        local_port = self.port if mode == "host" else 0
        try:
            self.socket.bind(("0.0.0.0", local_port))
        except OSError:
            self.socket.close()
            raise
        self.peers = {}
        self.players = {}
        self.chat_messages = []
        self.last_send = 0.0
        self.last_seen = 0.0
        self.game_started = False

    def send_packet(self, packet, destination):
        try:
            self.socket.sendto(packet, destination)
        except OSError:
            pass

    def send_chat(self, text):
        message = {
            "kind": "chat",
            "id": self.player_id,
            "name": self.name,
            "text": text[:80],
        }
        packet = json.dumps(message).encode("utf-8")
        if self.mode == "host":
            for peer in self.peers.values():
                self.send_packet(packet, peer)
        else:
            self.send_packet(packet, self.address)

    def drain_chat(self):
        messages = self.chat_messages
        self.chat_messages = []
        return messages

    def update(self, x, y, z, lobby=False):
        now = time.monotonic()
        packet = json.dumps({
            "kind": "state",
            "id": self.player_id,
            "name": self.name,
            "x": round(x, 3),
            "y": round(y, 3),
            "z": round(z, 3),
            "lobby": lobby,
        }).encode("utf-8")
        if now - self.last_send > 0.05:
            destination = None if self.mode == "host" else self.address
            if destination:
                self.send_packet(packet, destination)
            else:
                for peer in self.peers.values():
                    self.send_packet(packet, peer)
            self.last_send = now

        while True:
            try:
                raw, sender = self.socket.recvfrom(4096)
            except BlockingIOError:
                break
            except OSError:
                break
            try:
                message = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if self.mode == "host" and message.get("kind") == "state":
                peer_id = message.get("id")
                if isinstance(peer_id, str) and peer_id and peer_id != self.player_id:
                    self.peers[peer_id] = sender
                    self.players[peer_id] = (message, now)
                    self.last_seen = now
            elif self.mode == "host" and message.get("kind") == "chat":
                self.chat_messages.append(message)
                for peer in self.peers.values():
                    self.send_packet(raw, peer)
            elif self.mode == "join" and message.get("kind") == "snapshot":
                self.players = {item["id"]: (item, now) for item in message.get("players", [])}
                self.last_seen = now
            elif self.mode == "join" and message.get("kind") == "chat":
                self.chat_messages.append(message)
            elif self.mode == "join" and message.get("kind") == "start":
                self.game_started = True

        if self.mode == "host":
            self.players[self.player_id] = ({"id": self.player_id, "name": self.name, "x": x, "y": y, "z": z}, now)
            for player_id, (_, updated) in list(self.players.items()):
                if player_id != self.player_id and now - updated >= 3:
                    self.players.pop(player_id, None)
                    self.peers.pop(player_id, None)
            if lobby:
                ready_players = [item for item, updated in self.players.values() if item.get("lobby") and item.get("z", 0) >= LOBBY_BUTTON_Z - 2]
                expected_players = len(self.peers) + 1
                if expected_players > 0 and len(ready_players) >= expected_players:
                    self.game_started = True
                    start_packet = json.dumps({"kind": "start"}).encode("utf-8")
                    for peer in self.peers.values():
                        self.send_packet(start_packet, peer)
            snapshot = json.dumps({
                "kind": "snapshot",
                "players": [item for item, updated in self.players.values() if now - updated < 3],
            }).encode("utf-8")
            for peer in self.peers.values():
                self.send_packet(snapshot, peer)

        return [item for player_id, (item, updated) in self.players.items()
                if player_id != self.player_id and now - updated < 3]

    def close(self):
        self.socket.close()

    def status(self):
        return "CONNECTED" if self.last_seen and time.monotonic() - self.last_seen < 3 else "WAITING FOR HOST..."


def project(point, camera):
    x, y, z = point
    yaw = camera[3] if len(camera) > 3 else 0
    pitch = camera[4] if len(camera) > 4 else 0
    relative_x = x - camera[0]
    relative_z = z - camera[2]
    view_x = relative_x * math.cos(yaw) - relative_z * math.sin(yaw)
    flat_depth = relative_x * math.sin(yaw) + relative_z * math.cos(yaw)
    relative_y = y - camera[1]
    view_y = relative_y * math.cos(pitch) - flat_depth * math.sin(pitch)
    depth = flat_depth * math.cos(pitch) + relative_y * math.sin(pitch)
    if depth <= 0.2:
        return None
    scale = FOCAL_LENGTH / depth
    return (int(SCREEN_WIDTH / 2 + view_x * scale), int(HORIZON - view_y * scale))


def camera_space_depth(point, camera):
    """Return a point's forward distance from the active camera."""
    x, y, z = point
    yaw = camera[3] if len(camera) > 3 else 0
    pitch = camera[4] if len(camera) > 4 else 0
    relative_x = x - camera[0]
    relative_z = z - camera[2]
    flat_depth = relative_x * math.sin(yaw) + relative_z * math.cos(yaw)
    return flat_depth * math.cos(pitch) + (y - camera[1]) * math.sin(pitch)


def cube_polygons(center, size, camera, exclude_top=False):
    cx, cy, cz = center
    width, height, depth = size
    x0, x1 = cx - width / 2, cx + width / 2
    y0, y1 = cy, cy + height
    z0, z1 = cz - depth / 2, cz + depth / 2
    vertices = [
        (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
        (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1),
    ]
    faces = ((0, 1, 2, 3), (4, 5, 6, 7), (0, 4, 7, 3), (1, 5, 6, 2), (3, 2, 6, 7))
    yaw = camera[3] if len(camera) > 3 else 0
    pitch = camera[4] if len(camera) > 4 else 0
    polygons = []
    for face_index, face in enumerate(faces):
        if exclude_top and face_index == 4:
            continue
        camera_depths = []
        for index in face:
            vertex_x, vertex_y, vertex_z = vertices[index]
            relative_x = vertex_x - camera[0]
            relative_z = vertex_z - camera[2]
            flat_depth = relative_x * math.sin(yaw) + relative_z * math.cos(yaw)
            relative_y = vertex_y - camera[1]
            camera_depths.append(flat_depth * math.cos(pitch) + relative_y * math.sin(pitch))
        if min(camera_depths) <= 0.45:
            continue
        points = [project(vertices[index], camera) for index in face]
        if None not in points:
            polygons.append((sum(camera_depths) / 4, points))
    return polygons


def shade(color, amount):
    return tuple(max(0, min(255, channel + amount)) for channel in color)


def draw_model_cube(screen, camera, center, size, texture, scale=0):
    faces = sorted(cube_polygons(center, size, camera), reverse=True)
    for index, (_, polygon) in enumerate(faces):
        pygame.draw.polygon(screen, shade(texture_color(texture, center[2], index), scale - index * 8), polygon)


def draw_3d_line(screen, camera, start, end, color, width):
    first = project(start, camera)
    second = project(end, camera)
    if first and second:
        pygame.draw.line(screen, color, first, second, width)


def draw_shadow(screen, camera, x, z, width=0.8, ground_y=0):
    yaw = camera[3] if len(camera) > 3 else 0
    pitch = camera[4] if len(camera) > 4 else 0
    relative_x = x - camera[0]
    relative_z = z - camera[2]
    flat_depth = relative_x * math.sin(yaw) + relative_z * math.cos(yaw)
    shadow_y = ground_y + 0.06
    camera_depth = flat_depth * math.cos(pitch) + (shadow_y - camera[1]) * math.sin(pitch)
    if camera_depth <= 1.0:
        return
    point = project((x, shadow_y, z), camera)
    if point:
        radius = min(72, max(5, int(FOCAL_LENGTH / camera_depth * width)))
        alpha = max(35, min(125, int(125 * min(1, camera_depth / 12))))
        shadow = pygame.Surface((radius * 2, max(3, radius // 2)), pygame.SRCALPHA)
        pygame.draw.ellipse(shadow, (20, 58, 38, alpha), shadow.get_rect())
        screen.blit(shadow, (point[0] - radius, point[1] - radius // 3))


def make_level(world_id=1):
    if world_id == 2:
        platforms = [(0, 0, 58, 9, 1.5, 116), (-2.8, 2.2, 18, 2.5, 0.7, 3),
                     (2.8, 2.8, 29, 2.5, 0.7, 3), (-2.4, 3.4, 42, 2.5, 0.7, 3),
                     (2.4, 2.3, 55, 2.5, 0.7, 3), (-2.5, 3.1, 70, 2.5, 0.7, 3),
                     (2.5, 2.5, 85, 2.5, 0.7, 3), (0, 4.0, 99, 3, 0.7, 3)]
        coins = [(-2.8, 3.4, 18), (2.8, 4.0, 29), (-2.4, 4.6, 42),
                 (2.4, 3.5, 55), (-2.5, 4.3, 70), (2.5, 3.7, 85), (0, 5.2, 99)]
        enemies = [(2, 1.5, 15), (-2, 1.5, 27), (2, 1.5, 40), (-2, 1.5, 58),
                   (2, 1.5, 74), (-2, 1.5, 92)]
    elif world_id == 3:
        platforms = [(0, 0, 58, 9, 1.5, 116), (0, 2.2, 20, 2.8, 0.7, 3),
                     (-2.8, 3.0, 34, 2.8, 0.7, 3), (2.8, 2.6, 48, 2.8, 0.7, 3),
                     (-2.8, 3.4, 64, 2.8, 0.7, 3), (2.8, 2.8, 80, 2.8, 0.7, 3),
                     (0, 4.5, 96, 3.5, 0.7, 3)]
        coins = [(0, 3.4, 20), (-2.8, 4.2, 34), (2.8, 3.8, 48),
                 (-2.8, 4.6, 64), (2.8, 4.0, 80), (0, 5.7, 96)]
        enemies = [(-2, 1.5, 12), (2, 1.5, 25), (-2, 1.5, 42), (2, 1.5, 57),
                   (-2, 1.5, 74), (2, 1.5, 90)]
    else:
        platforms = [(0, 0, 58, 9, 1.5, 116),
                     (-2.6, 2.8, 27, 2.4, 0.7, 3), (2.4, 2.4, 39, 2.6, 0.7, 3),
                     (-2.5, 2.5, 58, 2.8, 0.7, 3), (2.5, 2.6, 76, 2.6, 0.7, 3)]
        coins = [(-2, 2, 21), (0, 2, 25), (2, 2, 31), (-2.6, 4.1, 27),
                 (2.4, 3.7, 39), (-2.5, 3.8, 58), (1.5, 2, 69), (2.5, 3.8, 76),
                 (-1.5, 2, 88), (0, 2, 95)]
        enemies = [(-2, 1.5, 17), (2, 1.5, 34), (-1.5, 1.5, 51), (2, 1.5, 70), (-2, 1.5, 88)]
    return platforms, coins, enemies


def make_test_npcs():
    return [
        {"id": "npc-peach", "name": "Peach [NPC]", "x": -2.0, "y": 1.5, "z": 12.0, "dx": 0.03, "dz": 0.02, "jump": 0.0},
        {"id": "npc-toad", "name": "Toad [NPC]", "x": 2.0, "y": 1.5, "z": 23.0, "dx": -0.02, "dz": 0.03, "jump": 0.0},
        {"id": "npc-yoshi", "name": "Yoshi [NPC]", "x": -1.5, "y": 1.5, "z": 36.0, "dx": 0.03, "dz": -0.02, "jump": 0.0},
        {"id": "npc-luigi", "name": "Luigi [NPC]", "x": 1.5, "y": 1.5, "z": 52.0, "dx": -0.03, "dz": -0.02, "jump": 0.0},
    ]


def update_test_npcs(npcs):
    for npc in npcs:
        if random.random() < 0.025:
            npc["dx"] = random.uniform(-0.045, 0.045)
            npc["dz"] = random.uniform(-0.045, 0.045)
        if random.random() < 0.006 and npc["y"] <= 1.5:
            npc["jump"] = 0.2
        npc["x"] += npc["dx"]
        npc["z"] += npc["dz"]
        npc["jump"] -= 0.012
        npc["y"] += npc["jump"]
        if npc["y"] < 1.5:
            npc["y"] = 1.5
            npc["jump"] = 0.0
        if npc["x"] < -3.8 or npc["x"] > 3.8:
            npc["dx"] *= -1
            npc["x"] = max(-3.8, min(3.8, npc["x"]))
        if npc["z"] < 4 or npc["z"] > WORLD_END - 4:
            npc["dz"] *= -1
            npc["z"] = max(4, min(WORLD_END - 4, npc["z"]))


def draw_mario_model(screen, camera, x, y, z, textures, facing_yaw=0.0, show_face=False, ground_y=None, graphics_quality=2):
    """Draw Mario facing his movement direction, rather than the camera."""
    if MARIO_MESHES:
        vertices = [vertex for positions, _, _, _, _ in MARIO_MESHES for vertex in positions]
        min_x, max_x = min(v[0] for v in vertices), max(v[0] for v in vertices)
        min_y, max_y = min(v[1] for v in vertices), max(v[1] for v in vertices)
        min_z, max_z = min(v[2] for v in vertices), max(v[2] for v in vertices)
        # Normalize the source model around its feet and fit the game's 2.1-unit character height.
        scale = 2.1 / max(0.001, max_y - min_y)
        center_x, center_z = (min_x + max_x) / 2, (min_z + max_z) / 2
        right_x, right_z = math.cos(facing_yaw), -math.sin(facing_yaw)
        forward_x, forward_z = math.sin(facing_yaw), math.cos(facing_yaw)
        if graphics_quality >= 2:
            draw_shadow(screen, camera, x, z, 0.72, y if ground_y is None else ground_y)
        polygons = []
        material_textures = textures.get("mario_materials", ())
        for positions, indices, color, uvs, material_index in MARIO_MESHES:
            for index in range(0, len(indices) - 2, 3):
                points3 = []
                triangle_indices = indices[index:index + 3]
                for vertex_index in triangle_indices:
                    vx, vy, vz = positions[vertex_index]
                    lx, lz = (vx - center_x) * scale, (vz - center_z) * scale
                    points3.append((x + lx * right_x + lz * forward_x,
                                    y + (vy - min_y) * scale,
                                    z + lx * right_z + lz * forward_z))
                points2 = [project(point, camera) for point in points3]
                if all(points2):
                    depth = sum(camera_space_depth(point, camera) for point in points3) / 3
                    face_color = color
                    material_texture = (material_textures[material_index]
                                        if material_index < len(material_textures) else None)
                    if graphics_quality < 2 or material_index == 3:
                        material_texture = None
                    if material_texture:
                        u = sum(uvs[i][0] for i in triangle_indices) / 3
                        v = sum(uvs[i][1] for i in triangle_indices) / 3
                        tx = int((u % 1.0) * (material_texture.get_width() - 1))
                        ty = int(((1 - v) % 1.0) * (material_texture.get_height() - 1))
                        texel = material_texture.get_at((tx, ty))
                        if texel.a < 16:
                            continue
                        face_color = tuple(texel[i] for i in range(3))
                    polygons.append((depth, points2, face_color))
        for _, polygon, color in sorted(polygons, key=lambda item: item[0], reverse=True):
            pygame.draw.polygon(screen, color, polygon)
        return

    right_x, right_z = math.cos(facing_yaw), -math.sin(facing_yaw)
    forward_x, forward_z = math.sin(facing_yaw), math.cos(facing_yaw)

    def point(local_x, local_y, local_forward=0):
        return (x + local_x * right_x + local_forward * forward_x,
                y + local_y,
                z + local_x * right_z + local_forward * forward_z)

    def cube(local_x, local_y, local_forward, size, texture, scale=0):
        width, height, depth = size
        # Axis-aligned cubes approximate the rotated model while retaining the
        # renderer's simple, fast cube drawing.
        rotated_size = (abs(width * right_x) + abs(depth * forward_x), height,
                        abs(width * right_z) + abs(depth * forward_z))
        draw_model_cube(screen, camera, point(local_x, local_y, local_forward), rotated_size, texture, scale)

    if graphics_quality >= 2:
        draw_shadow(screen, camera, x, z, 0.72, y if ground_y is None else ground_y)
    for leg_x in (-0.29, 0.29):
        cube(leg_x, 0.05, 0.03, (0.34, 0.58, 0.42), textures["overalls"], -3)
        cube(leg_x, 0.01, -0.07, (0.46, 0.18, 0.50), textures["shoe"], -2)

    cube(0, 0.56, 0, (1.02, 0.78, 0.62), textures["mario"], -2)
    cube(0, 0.70, 0.33, (0.78, 0.53, 0.10), textures["overalls"], 2)
    # A blue rear panel keeps Mario recognizable when the third-person camera
    # follows behind him.
    cube(0, 0.70, -0.33, (0.86, 0.60, 0.10), textures["overalls"], 1)
    for arm_x in (-0.61, 0.61):
        cube(arm_x, 0.75, -0.01, (0.24, 0.52, 0.40), textures["mario"], -1)
        cube(arm_x, 0.57, -0.10, (0.25, 0.25, 0.33), textures["glove"], 1)

    cube(0, 1.34, 0, (0.84, 0.70, 0.66), textures["skin"], 3)
    for hair_x in (-0.43, 0.43):
        cube(hair_x, 1.45, 0.19, (0.14, 0.42, 0.18), textures["hair"], -1)
    cube(0, 1.48, -0.35, (0.66, 0.34, 0.10), textures["hair"], -2)
    cube(0, 1.94, 0, (0.98, 0.24, 0.72), textures["cap"], 1)
    cube(0, 1.92, 0.40, (1.10, 0.10, 0.18), textures["cap"], -1)

    if not show_face:
        return

    cube(0, 1.59, 0.38, (0.18, 0.21, 0.16), textures["skin"], 7)
    for mustache_x in (-0.15, 0.15):
        cube(mustache_x, 1.51, 0.39, (0.28, 0.13, 0.09), textures["hair"], -6)
    for eye_x in (-0.17, 0.17):
        eye = project(point(eye_x, 1.75, 0.35), camera)
        if eye:
            pygame.draw.circle(screen, WHITE, eye, 5)
            pygame.draw.circle(screen, (45, 89, 175), (eye[0], eye[1] + 1), 2)
    for button_x in (-0.20, 0.20):
        button = project(point(button_x, 1.04, 0.40), camera)
        if button:
            pygame.draw.circle(screen, GOLD, button, 4)
            pygame.draw.circle(screen, (174, 113, 28), button, 1)
    badge = project(point(0, 2.06, 0.39), camera)
    if badge:
        pygame.draw.circle(screen, WHITE, badge, 7)
        pygame.draw.lines(screen, RED, False, ((badge[0] - 3, badge[1] + 3), (badge[0] - 3, badge[1] - 3), badge, (badge[0] + 3, badge[1] - 3), (badge[0] + 3, badge[1] + 3)), 2)


class Player:
    def __init__(self):
        self.x, self.y, self.z = 0.0, 1.5, 5.0
        self.velocity_y = 0.0
        self.on_ground = True
        self.lives = 3
        self.facing_yaw = 0.0
        self.ground_y = 1.5

    def respawn(self):
        self.x, self.y, self.z = 0.0, 1.5, 5.0
        self.velocity_y = 0.0
        self.on_ground = True
        self.ground_y = 1.5

    def update(self, keys, platforms, sounds, camera_yaw=0):
        speed = 0.11
        right_x = math.cos(camera_yaw) * speed
        right_z = -math.sin(camera_yaw) * speed
        forward_x = math.sin(camera_yaw) * speed
        forward_z = math.cos(camera_yaw) * speed
        move_x = 0.0
        move_z = 0.0
        if keys[pygame.K_LEFT] or keys[pygame.K_a]:
            move_x -= right_x
            move_z -= right_z
        if keys[pygame.K_RIGHT] or keys[pygame.K_d]:
            move_x += right_x
            move_z += right_z
        if keys[pygame.K_UP] or keys[pygame.K_w]:
            move_x += forward_x
            move_z += forward_z
        if keys[pygame.K_DOWN] or keys[pygame.K_s]:
            move_x -= forward_x
            move_z -= forward_z
        if move_x or move_z:
            self.x += move_x
            self.z += move_z
            self.facing_yaw = math.atan2(move_x, move_z)
        if keys[pygame.K_SPACE] and self.on_ground:
            self.velocity_y = 0.23
            self.on_ground = False
            if "jump" in sounds:
                sounds["jump"].play()

        self.velocity_y -= 0.012
        previous_y = self.y
        self.y += self.velocity_y
        landing_height = None
        for px, py, pz, width, height, depth in platforms:
            inside = abs(self.x - px) < (width + 0.8) / 2 and abs(self.z - pz) < (depth + 0.8) / 2
            top = py + height
            if inside and previous_y >= top and self.y <= top and self.velocity_y <= 0:
                landing_height = top if landing_height is None else max(landing_height, top)
        self.on_ground = landing_height is not None
        if landing_height is not None:
            self.y = landing_height
            self.velocity_y = 0
            self.ground_y = landing_height
        self.x = max(-4.3, min(4.3, self.x))

    def draw(self, screen, camera, textures, graphics_quality=2):
        draw_mario_model(screen, camera, self.x, self.y, self.z, textures, self.facing_yaw,
                         ground_y=self.ground_y, graphics_quality=graphics_quality)


def third_person_camera(player, yaw, look_pitch):
    """Keep a fixed, player-centered follow camera aimed at Mario."""
    follow_distance = 7.0
    camera_height = 3.2
    target_height = 1.25
    camera_x = player.x - math.sin(yaw) * follow_distance
    camera_y = player.y + camera_height
    camera_z = player.z - math.cos(yaw) * follow_distance
    target_pitch = math.atan2(target_height - camera_height, follow_distance)
    return (camera_x, camera_y, camera_z, yaw, target_pitch + look_pitch * 0.35)


class Enemy:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z
        self.direction = random.choice((-1, 1))
        self.kind = "koopa" if int(z) % 3 == 0 else "goomba"
        self.speed = 0.025 if self.kind == "goomba" else 0.035
        self.phase = random.random() * math.tau
        self.animation_time = (random.random() * GOOMBA_ANIMATION["duration"]
                              if GOOMBA_ANIMATION else 0.0)
        # Both enemy types patrol along the course, turning around at its ends.
        self.axis = "z"

    def update(self, platforms=()):
        self.phase += 0.12
        if GOOMBA_ANIMATION:
            self.animation_time = (self.animation_time + 1 / FPS) % GOOMBA_ANIMATION["duration"]
        next_z = self.z + self.direction * self.speed
        blocked = next_z < 4.5 or next_z > WORLD_END - 4.5
        # Treat raised level blocks as solid obstacles. The ground platform is
        # support, not a wall, so only blocks that overlap the enemy's body stop it.
        for px, py, pz, width, height, depth in platforms:
            if py + height <= self.y + 0.02 or py >= self.y + 1.2:
                continue
            if (abs(self.x - px) < (width + 1.25) / 2
                    and abs(next_z - pz) < (depth + 0.9) / 2
                    and self.y < py + height):
                blocked = True
                break
        if blocked:
            self.direction *= -1
        else:
            self.z = next_z

    def overlaps_player(self, player):
        """Check horizontal contact and vertical body overlap separately."""
        horizontal_distance = math.hypot(player.x - self.x, player.z - self.z)
        vertical_overlap = player.y < self.y + 1.2 and player.y + 1.7 > self.y
        return horizontal_distance < 0.9 and vertical_overlap

    def draw(self, screen, camera, textures, graphics_quality=2):
        bob = math.sin(self.phase) * 0.035
        if graphics_quality >= 2:
            draw_shadow(screen, camera, self.x, self.z, 0.75, self.y)
        if self.kind == "koopa":
            draw_model_cube(screen, camera, (self.x, self.y + 0.38 + bob, self.z), (1.35, 1.0, 0.9), textures["shell"], 0)
            draw_model_cube(screen, camera, (self.x, self.y + 1.05 + bob, self.z - 0.18), (0.62, 0.65, 0.62), textures["skin"], 5)
            for eye_x in (self.x - 0.14, self.x + 0.14):
                eye = project((eye_x, self.y + 1.25 + bob, self.z - 0.5), camera)
                if eye:
                    pygame.draw.circle(screen, WHITE, eye, 5)
                    pygame.draw.circle(screen, INK, (eye[0], eye[1] + 1), 2)
            draw_3d_line(screen, camera, (self.x - 0.36, self.y + 0.02, self.z - 0.1), (self.x - 0.62, self.y - 0.03, self.z - 0.27), (247, 190, 140), 7)
            draw_3d_line(screen, camera, (self.x + 0.36, self.y + 0.02, self.z - 0.1), (self.x + 0.62, self.y - 0.03, self.z - 0.27), (247, 190, 140), 7)
        else:
            if GOOMBA_ANIMATION and textures.get("goomba_model"):
                frames = GOOMBA_ANIMATION["frames"]
                frame_index = min(len(frames) - 1, int(
                    self.animation_time / GOOMBA_ANIMATION["duration"] * len(frames)))
                vertices = frames[frame_index]
                indices = GOOMBA_ANIMATION["indices"]
                uvs = GOOMBA_ANIMATION["uvs"]
                texture = textures["goomba_model"]
                polygons = []
                facing = 1 if self.direction > 0 else -1
                for index in range(0, len(indices) - 2, 3):
                    triangle = indices[index:index + 3]
                    points3 = []
                    for vertex_index in triangle:
                        vx, vy, vz = vertices[vertex_index]
                        points3.append((self.x + vx * facing,
                                        self.y + vy + bob,
                                        self.z + vz * facing))
                    points2 = [project(point, camera) for point in points3]
                    if not all(points2):
                        continue
                    u = sum(uvs[i][0] for i in triangle) / 3
                    v = sum(uvs[i][1] for i in triangle) / 3
                    tx = int((u % 1.0) * (texture.get_width() - 1))
                    ty = int(((1 - v) % 1.0) * (texture.get_height() - 1))
                    color = (texture.get_at((tx, ty))[:3] if graphics_quality >= 1
                             else (155, 70, 30))
                    depth = sum(camera_space_depth(point, camera) for point in points3) / 3
                    polygons.append((depth, points2, color))
                for _, polygon, color in sorted(polygons, key=lambda item: item[0], reverse=True):
                    pygame.draw.polygon(screen, color, polygon)
                # Put the atlas face back over the coarse triangle samples: the
                # white eye texels should remain eyes, not fill the entire face.
                face = textures.get("enemy_face")
                face_y = self.y + 0.76 + bob
                face_z = self.z + facing * 0.49
                face_top = project((self.x, face_y + 0.35, face_z), camera)
                face_bottom = project((self.x, face_y - 0.35, face_z), camera)
                face_left = project((self.x - 0.42, face_y, face_z), camera)
                face_right = project((self.x + 0.42, face_y, face_z), camera)
                if face and face_top and face_bottom and face_left and face_right:
                    face_width = max(1, abs(face_right[0] - face_left[0]))
                    face_height = max(1, abs(face_bottom[1] - face_top[1]))
                    face_sprite = pygame.transform.smoothscale(face, (face_width, face_height))
                    if facing < 0:
                        face_sprite = pygame.transform.flip(face_sprite, True, False)
                    screen.blit(face_sprite, (min(face_left[0], face_right[0]), face_top[1]))
                return

            # Draw the Goomba as one rounded body in screen space. The cube-only
            # body made the face atlas look like a sticker on a pair of blocks.
            body_top = project((self.x, self.y + 1.2 + bob, self.z - 0.47), camera)
            body_bottom = project((self.x, self.y + 0.03 + bob, self.z - 0.47), camera)
            body_left = project((self.x - 0.62, self.y + 0.62 + bob, self.z - 0.47), camera)
            body_right = project((self.x + 0.62, self.y + 0.62 + bob, self.z - 0.47), camera)
            if body_top and body_bottom and body_left and body_right:
                body_width = max(1, abs(body_right[0] - body_left[0]))
                body_height = max(1, abs(body_bottom[1] - body_top[1]))
                body_rect = pygame.Rect(body_left[0], body_top[1], body_width, body_height)
                pygame.draw.ellipse(screen, (116, 53, 25), body_rect)
                pygame.draw.ellipse(screen, (151, 70, 30), body_rect.inflate(-body_width // 7, -body_height // 10))
                foot_y = body_bottom[1] - max(2, body_height // 12)
                foot_width = max(3, body_width // 3)
                foot_height = max(2, body_height // 8)
                pygame.draw.ellipse(screen, (47, 27, 24), (body_rect.centerx - foot_width - 2, foot_y, foot_width, foot_height))
                pygame.draw.ellipse(screen, (47, 27, 24), (body_rect.centerx + 2, foot_y, foot_width, foot_height))
            face = textures.get("enemy_face")
            face_top = project((self.x, self.y + 1.10 + bob, self.z - 0.47), camera)
            face_bottom = project((self.x, self.y + 0.38 + bob, self.z - 0.47), camera)
            face_left = project((self.x - 0.43, self.y + 0.74 + bob, self.z - 0.47), camera)
            face_right = project((self.x + 0.43, self.y + 0.74 + bob, self.z - 0.47), camera)
            if face and face_top and face_bottom and face_left and face_right:
                face_width = max(1, abs(face_right[0] - face_left[0]))
                face_height = max(1, abs(face_bottom[1] - face_top[1]))
                face_sprite = pygame.transform.smoothscale(face, (face_width, face_height))
                screen.blit(face_sprite, (face_left[0], face_top[1]))
            draw_3d_line(screen, camera, (self.x - 0.45, self.y + 0.03, self.z - 0.16), (self.x - 0.7, self.y - 0.02, self.z - 0.3), INK, 8)
            draw_3d_line(screen, camera, (self.x + 0.45, self.y + 0.03, self.z - 0.16), (self.x + 0.7, self.y - 0.02, self.z - 0.3), INK, 8)


def draw_remote_player(screen, camera, player, textures, font, graphics_quality=2):
    x, y, z = player["x"], player["y"], player["z"]
    draw_mario_model(screen, camera, x, y, z, textures, graphics_quality=graphics_quality)


def draw_nameplate(screen, camera, x, y, z, name, font, color=WHITE):
    name_point = project((x, y + 2.05, z), camera)
    if name_point:
        label_text = name[:16]
        label = font.render(label_text, True, WHITE)
        outline = font.render(label_text, True, (0, 0, 0))
        background = pygame.Surface((label.get_width() + 10, label.get_height() + 4), pygame.SRCALPHA)
        background.fill((18, 25, 53, 210))
        for offset_x, offset_y in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            background.blit(outline, (5 + offset_x, 2 + offset_y))
        background.blit(label, (5, 2))
        x_position = max(4, min(SCREEN_WIDTH - background.get_width() - 4, name_point[0] - background.get_width() // 2))
        screen.blit(background, (x_position, name_point[1] - background.get_height() // 2))


def draw_chat_bubble(screen, camera, x, y, z, text, font):
    bubble_point = project((x, y + 2.62, z), camera)
    if bubble_point:
        label = font.render(text[:42], True, INK)
        bubble = pygame.Surface((label.get_width() + 16, label.get_height() + 10), pygame.SRCALPHA)
        bubble.fill((255, 255, 255, 238))
        pygame.draw.rect(bubble, (35, 46, 73), bubble.get_rect(), 2, border_radius=7)
        bubble.blit(label, (8, 5))
        x_position = max(4, min(SCREEN_WIDTH - bubble.get_width() - 4, bubble_point[0] - bubble.get_width() // 2))
        screen.blit(bubble, (x_position, bubble_point[1] - bubble.get_height() // 2))


def draw_leaderboard(screen, font, local_name, local_z, remote_players):
    players = [(local_name, max(0, int(local_z - 5)), True)]
    players.extend((item["name"], max(0, int(item["z"] - 5)), False) for item in remote_players)
    players.sort(key=lambda item: item[1], reverse=True)
    panel = pygame.Surface((265, 46 + 25 * len(players)), pygame.SRCALPHA)
    panel.fill((18, 25, 53, 220))
    pygame.draw.rect(panel, GOLD, (0, 0, panel.get_width(), 4))
    panel.blit(font.render("DISTANCE LEADERBOARD", True, GOLD), (12, 10))
    for row, (name, distance, is_local) in enumerate(players):
        color = GOLD if is_local else WHITE
        panel.blit(font.render(f"{row + 1}. {name[:13]}", True, color), (14, 34 + row * 25))
        value = font.render(f"{distance} m", True, color)
        panel.blit(value, (panel.get_width() - value.get_width() - 14, 34 + row * 25))
    screen.blit(panel, (SCREEN_WIDTH - panel.get_width() - 14, 58))


def draw_first_person_hands(screen, camera, textures, graphics_quality=2):
    """Draw the rig's static glove meshes as view-locked first-person hands."""
    if MARIO_MESHES and MARIO_HAND_MESHES:
        vertices = [vertex for positions, _, _, _, _ in MARIO_MESHES for vertex in positions]
        min_x, max_x = min(v[0] for v in vertices), max(v[0] for v in vertices)
        min_y, max_y = min(v[1] for v in vertices), max(v[1] for v in vertices)
        scale = 2.1 / max(0.001, max_y - min_y)
        center_x = (min_x + max_x) / 2
        yaw = camera[3] if len(camera) > 3 else 0.0
        pitch = camera[4] if len(camera) > 4 else 0.0
        right = (math.cos(yaw), 0.0, -math.sin(yaw))
        up = (-math.sin(yaw) * math.sin(pitch), math.cos(pitch),
              -math.cos(yaw) * math.sin(pitch))
        forward = (math.sin(yaw) * math.cos(pitch), math.sin(pitch),
                   math.cos(yaw) * math.cos(pitch))
        material_textures = textures.get("mario_materials", ())
        polygons = []
        for positions, indices, base_color, uvs, material_index in MARIO_HAND_MESHES:
            hand_center = tuple(sum(vertex[axis] for vertex in positions) / len(positions)
                                for axis in range(3))
            hand_side = 1 if hand_center[0] >= center_x else -1
            anchor_x, anchor_y, anchor_depth = hand_side * 0.62, -0.43, 1.45
            points3 = []
            for vx, vy, vz in positions:
                local_x = anchor_x + (vx - hand_center[0]) * scale
                local_y = anchor_y + (vy - hand_center[1]) * scale
                local_depth = anchor_depth + (vz - hand_center[2]) * scale
                points3.append(tuple(camera[axis] + right[axis] * local_x
                                     + up[axis] * local_y + forward[axis] * local_depth
                                     for axis in range(3)))
            material_texture = (material_textures[material_index]
                                if material_index < len(material_textures) else None)
            if graphics_quality < 2 or material_index == 3:
                material_texture = None
            for index in range(0, len(indices) - 2, 3):
                triangle_indices = indices[index:index + 3]
                points2 = [project(points3[vertex_index], camera)
                           for vertex_index in triangle_indices]
                if not all(point is not None for point in points2):
                    continue
                depth = sum(camera_space_depth(points3[vertex_index], camera)
                            for vertex_index in triangle_indices) / 3
                face_color = base_color
                if material_texture:
                    u = sum(uvs[i][0] for i in triangle_indices) / 3
                    v = sum(uvs[i][1] for i in triangle_indices) / 3
                    tx = int((u % 1.0) * (material_texture.get_width() - 1))
                    ty = int(((1 - v) % 1.0) * (material_texture.get_height() - 1))
                    texel = material_texture.get_at((tx, ty))
                    if texel.a < 16:
                        continue
                    face_color = tuple(texel[channel] for channel in range(3))
                polygons.append((depth, points2, face_color))
        for _, polygon, color in sorted(polygons, key=lambda item: item[0], reverse=True):
            pygame.draw.polygon(screen, color, polygon)
    pygame.draw.line(screen, WHITE, (SCREEN_WIDTH // 2 - 8, SCREEN_HEIGHT // 2), (SCREEN_WIDTH // 2 + 8, SCREEN_HEIGHT // 2), 2)
    pygame.draw.line(screen, WHITE, (SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 - 8), (SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 + 8), 2)


def draw_touch_controls(screen):
    controls = (
        (pygame.Rect(42, 414, 58, 58), "<"),
        (pygame.Rect(158, 414, 58, 58), ">"),
        (pygame.Rect(100, 356, 58, 58), "^"),
        (pygame.Rect(100, 472, 58, 58), "v"),
        (pygame.Rect(SCREEN_WIDTH - 132, 410, 92, 62), "JUMP"),
    )
    overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
    for button, label in controls:
        pygame.draw.rect(overlay, (18, 25, 53, 150), button, border_radius=12)
        pygame.draw.rect(overlay, (255, 211, 48, 190), button, 2, border_radius=12)
        font = pygame.font.Font(None, 25 if label == "JUMP" else 42)
        text = font.render(label, True, (255, 255, 255, 225))
        overlay.blit(text, (button.centerx - text.get_width() // 2, button.centery - text.get_height() // 2))
    hint_font = pygame.font.Font(None, 20)
    hint = hint_font.render("TOUCH CONTROLS", True, (255, 255, 255, 190))
    overlay.blit(hint, (SCREEN_WIDTH // 2 - hint.get_width() // 2, 505))
    screen.blit(overlay, (0, 0))


def draw_lobby_button(screen, camera, font, ready):
    base = project((0, 0, LOBBY_BUTTON_Z), camera)
    top = project((0, 0.35, LOBBY_BUTTON_Z), camera)
    if base and top:
        radius = max(8, abs(top[1] - base[1]) * 2)
        color = (68, 220, 94) if ready else (35, 155, 63)
        pygame.draw.ellipse(screen, color, (base[0] - radius, base[1] - radius // 2, radius * 2, radius))
        pygame.draw.ellipse(screen, (154, 255, 145), (base[0] - radius // 2, base[1] - radius // 3, radius, max(3, radius // 3)))
        label = font.render("START", True, WHITE)
        screen.blit(label, (base[0] - label.get_width() // 2, base[1] - radius - label.get_height() - 6))


class TouchInput:
    def __init__(self, points):
        self.points = points

    def __getitem__(self, key):
        keyboard = pygame.key.get_pressed()
        return keyboard[key] or key in self.active_keys()

    def active_keys(self):
        active = set()
        for x, y in self.points.values():
            if pygame.Rect(42, 414, 58, 58).collidepoint(x, y):
                active.add(pygame.K_LEFT)
            if pygame.Rect(158, 414, 58, 58).collidepoint(x, y):
                active.add(pygame.K_RIGHT)
            if pygame.Rect(100, 356, 58, 58).collidepoint(x, y):
                active.add(pygame.K_UP)
            if pygame.Rect(100, 472, 58, 58).collidepoint(x, y):
                active.add(pygame.K_DOWN)
            if pygame.Rect(SCREEN_WIDTH - 132, 410, 92, 62).collidepoint(x, y):
                active.add(pygame.K_SPACE)
        return active


def draw_text(screen, font, text, position, color=WHITE):
    screen.blit(font.render(text, True, INK), (position[0] + 2, position[1] + 2))
    screen.blit(font.render(text, True, color), position)


def draw_background(screen, camera, graphics_quality=2):
    graphics_quality = max(0, min(4, graphics_quality))
    pitch = camera[4] if len(camera) > 4 else 0
    horizon_shift = int(pitch * 90)
    if graphics_quality == 0:
        screen.fill((92, 180, 235))
    else:
        for row in range(SCREEN_HEIGHT):
            blend = min(1, row / max(1, 360 + horizon_shift))
            color = tuple(int(SKY[channel] * (1 - blend) + (53, 121, 151)[channel] * blend) for channel in range(3))
            pygame.draw.line(screen, color, (0, row), (SCREEN_WIDTH, row))
    sun = (780, 98 + horizon_shift // 3)
    if graphics_quality >= 3:
        pygame.draw.circle(screen, (255, 221, 123), sun, 64)
        pygame.draw.circle(screen, (255, 231, 148), sun, 55)
    pygame.draw.circle(screen, (255, 235, 151), sun, 35 + graphics_quality * 3)
    yaw = camera[3] if len(camera) > 3 else 0
    cloud_data = ((150, 110, 1.0), (420, 75, 0.8), (780, 155, 1.25), (1110, 95, 0.7))
    cloud_counts = (1, 2, 3, 4, 4)
    for cloud_index, (cloud_x, cloud_y, cloud_scale) in enumerate(cloud_data[:cloud_counts[graphics_quality]]):
        x = int((cloud_x - math.sin(yaw) * 150 - camera[0] * 18) % (SCREEN_WIDTH + 220) - 110)
        y = cloud_y + horizon_shift // 4
        radius = int(24 * cloud_scale)
        cloud_color = (245, 250, 255)
        if graphics_quality >= 3:
            shade_color = (207, 231, 245)
            pygame.draw.ellipse(screen, shade_color, (x, y + 5, radius * 2, radius))
        pygame.draw.circle(screen, cloud_color, (x, y), radius)
        pygame.draw.circle(screen, cloud_color, (x + radius, y + 6), int(radius * 1.25))
        pygame.draw.circle(screen, cloud_color, (x + radius * 2, y), int(radius * 0.9))
    if graphics_quality >= 1:
        pygame.draw.polygon(screen, (82, 177, 113), [(0, 330 + horizon_shift), (170, 215 + horizon_shift), (360, 330 + horizon_shift)])
        pygame.draw.polygon(screen, (70, 163, 102), [(430, 330 + horizon_shift), (700, 190 + horizon_shift), (980, 330 + horizon_shift)])
    ground_top = max(300, 330 + horizon_shift)
    ground_color = (42, 126, 65) if graphics_quality == 0 else (56, 149, 78)
    pygame.draw.rect(screen, ground_color, (0, ground_top, SCREEN_WIDTH, SCREEN_HEIGHT - ground_top))
    if graphics_quality >= 4:
        for stripe in range(1, 6):
            y = ground_top + stripe * (SCREEN_HEIGHT - ground_top) // 6
            pygame.draw.line(screen, (60, 156, 81), (0, y), (SCREEN_WIDTH, y), 1)


def draw_ground_plane(screen, camera, graphics_quality=2):
    floor_faces = cube_polygons((0, 0, 58), (9, 0.18, 116), camera)
    floor_colors = ((49, 151, 73), (66, 176, 78), (39, 124, 65))
    for index, (_, polygon) in enumerate(sorted(floor_faces, reverse=True)):
        pygame.draw.polygon(screen, floor_colors[index % len(floor_colors)], polygon)


def floor_tile_polygon(x0, x1, y, z0, z1, camera):
    """Return a projected top-face tile with its camera depth."""
    vertices = ((x0, y, z0), (x1, y, z0), (x1, y, z1), (x0, y, z1))
    yaw = camera[3] if len(camera) > 3 else 0
    pitch = camera[4] if len(camera) > 4 else 0
    depths = []
    for vertex_x, vertex_y, vertex_z in vertices:
        relative_x = vertex_x - camera[0]
        relative_z = vertex_z - camera[2]
        flat_depth = relative_x * math.sin(yaw) + relative_z * math.cos(yaw)
        depths.append(flat_depth * math.cos(pitch) + (vertex_y - camera[1]) * math.sin(pitch))
    if min(depths) <= 0.45:
        return None
    polygon = [project(vertex, camera) for vertex in vertices]
    if None in polygon:
        return None
    return sum(depths) / len(depths), polygon


def add_floor_texture_tiles(objects, platform, camera, texture, tile_size=1.25):
    """Project a repeated floor texture as small colored tiles."""
    px, py, pz, width, height, depth = platform
    columns = math.ceil(width / tile_size)
    rows = math.ceil(depth / tile_size)
    left = px - width / 2
    near = pz - depth / 2
    texture_width, texture_height = texture.get_size()
    repeat_world_units = 2.5
    for column in range(columns):
        x0 = left + column * tile_size
        x1 = min(left + width, x0 + tile_size)
        texture_x = int((((column * tile_size + tile_size / 2) % repeat_world_units)
                         / repeat_world_units) * (texture_width - 1))
        for row in range(rows):
            z0 = near + row * tile_size
            z1 = min(near + depth, z0 + tile_size)
            tile = floor_tile_polygon(x0, x1, py + height + 0.01, z0, z1, camera)
            if tile:
                texture_y = int((((row * tile_size + tile_size / 2) % repeat_world_units)
                                 / repeat_world_units) * (texture_height - 1))
                objects.append((*tile, texture.get_at((texture_x, texture_y))[:3]))


def draw_world(screen, camera, platforms, coins, enemies, goal_z, textures, graphics_quality=2):
    objects = []
    for platform_index, platform in enumerate(platforms):
        px, py, pz, width, height, depth = platform
        texture = textures["floor"] if py == 0 else textures["brick"]
        color = texture_color(texture, pz, platform_index)
        if py == 0 and depth > 20:
            tile_sizes = (0, 1.25, 0.55, 0.4, 0.25)
            tile_size = tile_sizes[max(0, min(4, graphics_quality))]
            chunk_depth = 8.2
            chunk_count = math.ceil(depth / chunk_depth)
            ground_near = pz - depth / 2
            for chunk_index in range(chunk_count):
                chunk_start = ground_near + chunk_index * chunk_depth
                actual_depth = min(chunk_depth, depth - chunk_index * chunk_depth)
                if actual_depth > 0:
                    chunk_z = chunk_start + actual_depth / 2
                    objects.extend((depth_value, polygon, color)
                                   for depth_value, polygon in cube_polygons(
                                       (px, py, chunk_z), (width, height, actual_depth), camera,
                                       exclude_top=bool(tile_size)))
            if tile_size:
                add_floor_texture_tiles(objects, platform, camera, texture, tile_size)
        else:
            objects.extend((depth_value, polygon, color) for depth_value, polygon in cube_polygons((px, py, pz), (width, height, depth), camera))
    for _, polygon, color in sorted(objects, key=lambda item: item[0], reverse=True):
        pygame.draw.polygon(screen, color, polygon)
    for coin in coins:
        point = project(coin, camera)
        if point:
            radius = max(3, int(FOCAL_LENGTH / max(camera_space_depth(coin, camera), 1) * 0.18))
            coin_sprite = textures.get("coin_sprite")
            if coin_sprite:
                height = max(14, radius * 4)
                width = max(8, int(height * coin_sprite.get_width() / coin_sprite.get_height()))
                size = (width, height)
                sprite_cache = textures["coin_sprite_cache"]
                if size not in sprite_cache:
                    sprite_cache[size] = pygame.transform.smoothscale(coin_sprite, size)
                screen.blit(sprite_cache[size], (point[0] - width // 2, point[1] - height // 2))
            else:
                pygame.draw.circle(screen, texture_color(textures["coin"], coin[2], 0), point, radius)
                pygame.draw.circle(screen, (255, 239, 115), point, max(2, radius // 2))
    goal_base = project((0, 0, goal_z), camera)
    goal_top = project((0, 6, goal_z), camera)
    if goal_base and goal_top:
        pygame.draw.line(screen, WHITE, goal_base, goal_top, 6)
        pygame.draw.polygon(screen, RED, [goal_top, (goal_top[0] + 40, goal_top[1] + 18), (goal_top[0], goal_top[1] + 34)])


def draw_menu(screen, title_font, font, small_font, name, address, mode, focus, error, world_id=1, character_style=0, controls_visible=False, tutorial_visible=False, saved=False, options_visible=False, graphics_quality=2, view_mode="first", control_mode="auto", join_visible=False, join_kind="local", join_ip="127.0.0.1", join_port="50007", join_focus=0):
    time_value = pygame.time.get_ticks() / 1000
    screen.fill((12, 22, 49))
    for band in range(9):
        color = (18 + band * 3, 37 + band * 5, 79 + band * 7)
        pygame.draw.rect(screen, color, (0, band * 54, SCREEN_WIDTH, 55))
    for index in range(18):
        star_x = (index * 127 + 53) % SCREEN_WIDTH
        star_y = (index * 71 + 29) % 275
        pulse = 1 + int((math.sin(time_value * 2 + index) + 1) / 2)
        pygame.draw.rect(screen, (178, 205, 239), (star_x, star_y, pulse, pulse))
    pygame.draw.circle(screen, (255, 226, 133), (820, 100), 54)
    pygame.draw.circle(screen, (255, 241, 178), (820, 100), 42)
    pygame.draw.polygon(screen, (39, 105, 83), [(0, 400), (170, 267), (360, 400)])
    pygame.draw.polygon(screen, (29, 84, 73), [(380, 400), (650, 220), (980, 400)])
    pygame.draw.rect(screen, (25, 112, 71), (0, 400, SCREEN_WIDTH, 140))

    draw_text(screen, title_font, "SUPER MARIO PC & MOBILE", (52, 72), RED)
    controls_button = pygame.Rect(790, 24, 130, 40)
    options_button = pygame.Rect(430, 24, 160, 40)
    tutorial_button = pygame.Rect(610, 24, 160, 40)
    pygame.draw.rect(screen, (27, 45, 84), options_button, border_radius=8)
    pygame.draw.rect(screen, GOLD, options_button, 2, border_radius=8)
    draw_text(screen, small_font, "OPTIONS", (477, 35), GOLD)
    pygame.draw.rect(screen, (27, 45, 84), tutorial_button, border_radius=8)
    pygame.draw.rect(screen, GOLD, tutorial_button, 2, border_radius=8)
    draw_text(screen, small_font, "HOW TO PLAY", (632, 35), GOLD)
    pygame.draw.rect(screen, (27, 45, 84), controls_button, border_radius=8)
    pygame.draw.rect(screen, GOLD, controls_button, 2, border_radius=8)
    draw_text(screen, small_font, "CONTROLS", (812, 35), GOLD)

    left_panel = pygame.Rect(48, 158, 490, 276)
    right_panel = pygame.Rect(565, 158, 347, 276)
    for panel in (left_panel, right_panel):
        pygame.draw.rect(screen, (15, 27, 58), panel, border_radius=12)
        pygame.draw.rect(screen, (59, 91, 137), panel, 2, border_radius=12)
    pygame.draw.rect(screen, RED, (left_panel.x, left_panel.y, 7, left_panel.height), border_radius=4)
    pygame.draw.rect(screen, GOLD, (right_panel.x, right_panel.y, 7, right_panel.height), border_radius=4)

    draw_text(screen, font, "PLAYER PROFILE", (78, 180), WHITE)
    draw_text(screen, small_font, "Your name appears above your character", (78, 211), (153, 176, 216))
    name_box = pygame.Rect(78, 239, 420, 43)
    address_box = pygame.Rect(78, 312, 420, 43)
    for box, active in ((name_box, focus == 0), (address_box, focus == 1)):
        pygame.draw.rect(screen, (27, 45, 84), box, border_radius=7)
        pygame.draw.rect(screen, GOLD if active else (67, 95, 140), box, 2, border_radius=7)
    draw_text(screen, small_font, "NAME", (92, 249), (153, 176, 216))
    draw_text(screen, font, name or "Type your name", (170, 247), GOLD if focus == 0 else WHITE)
    draw_text(screen, small_font, "HOST IP", (92, 322), (153, 176, 216))
    draw_text(screen, font, address, (170, 320), GOLD if focus == 1 else WHITE)
    draw_text(screen, small_font, "WORLD", (92, 375), (153, 176, 216))
    for index in range(1, 4):
        world_box = pygame.Rect(170 + (index - 1) * 108, 367, 92, 34)
        selected = world_id == index
        pygame.draw.rect(screen, (72, 61, 52) if selected else (27, 45, 84), world_box, border_radius=6)
        pygame.draw.rect(screen, GOLD if selected else (67, 95, 140), world_box, 2, border_radius=6)
        draw_text(screen, small_font, f"{index}  WORLD {index}", (181 + (index - 1) * 108, 377), WHITE if selected else (181, 198, 225))
    draw_text(screen, small_font, "STYLE", (92, 415), (153, 176, 216))
    style_colors = ((198, 32, 40), (40, 93, 198), (112, 52, 164))
    for index, style_color in enumerate(style_colors):
        swatch = pygame.Rect(170 + index * 48, 407, 34, 24)
        pygame.draw.rect(screen, style_color, swatch, border_radius=5)
        pygame.draw.rect(screen, GOLD if character_style == index else (67, 95, 140), swatch, 2, border_radius=5)

    draw_text(screen, font, "GAME MODE", (594, 180), WHITE)
    mode_labels = (("F1", "SOLO", "Practice alone"), ("F2", "HOST", "Create a room"), ("F3", "JOIN", "Enter a room"), ("F4", "TEST", "NPC playground"))
    for index, (key, label, description) in enumerate(mode_labels):
        box = pygame.Rect(590, 218 + index * 42, 295, 34)
        selected = mode == label.lower()
        pygame.draw.rect(screen, (72, 61, 52) if selected else (27, 45, 84), box, border_radius=6)
        pygame.draw.rect(screen, GOLD if selected else (67, 95, 140), box, 2, border_radius=6)
        draw_text(screen, small_font, key, (604, 226 + index * 42), GOLD)
        draw_text(screen, font, label, (645, 221 + index * 42), WHITE if selected else (181, 198, 225))
        draw_text(screen, small_font, description, (735, 226 + index * 42), (181, 198, 225))

    if mode == "host":
        hint = "Share port 50007 with your friends"
    elif mode == "join":
        hint = "Enter the host computer's IP address"
    elif mode == "test":
        hint = "Practice with NPCs and extra enemies"
    else:
        hint = "Explore the course at your own pace"
    draw_text(screen, small_font, hint, (594, 392), (153, 176, 216))
    save_button = pygame.Rect(594, 405, 291, 34)
    pygame.draw.rect(screen, GOLD if saved else (27, 45, 84), save_button, border_radius=7)
    pygame.draw.rect(screen, GOLD, save_button, 2, border_radius=7)
    draw_text(screen, small_font, "PROFILE SAVED" if saved else "SAVE PROFILE", (684 if saved else 680, 414), INK if saved else GOLD)
    pygame.draw.rect(screen, GOLD, (48, 458, 864, 48), border_radius=10)
    draw_text(screen, font, "ENTER", (78, 470), INK)
    draw_text(screen, font, "START RUN", (170, 470), INK)
    draw_text(screen, small_font, "TAB switch field   |   BACKSPACE erase   |   ESC quit", (570, 474), INK)
    if error:
        draw_text(screen, small_font, error, (52, 510), (255, 133, 133))
    if controls_visible:
        overlay = pygame.Rect(220, 88, 520, 370)
        pygame.draw.rect(screen, (12, 20, 45), overlay, border_radius=14)
        pygame.draw.rect(screen, GOLD, overlay, 3, border_radius=14)
        draw_text(screen, title_font, "CONTROLS", (355, 112), GOLD)
        draw_text(screen, font, "W / UP       Move forward", (278, 202), WHITE)
        draw_text(screen, font, "S / DOWN     Move backward", (278, 238), WHITE)
        draw_text(screen, font, "A / LEFT     Strafe left", (278, 274), WHITE)
        draw_text(screen, font, "D / RIGHT    Strafe right", (278, 310), WHITE)
        draw_text(screen, font, "SPACE        Jump", (278, 346), WHITE)
        draw_text(screen, font, "Mouse X / Q-E Look left and right", (278, 382), WHITE)
        draw_text(screen, font, "Mouse Y / R-F Look up and down", (278, 418), WHITE)
        close_button = pygame.Rect(405, 438, 150, 34)
        pygame.draw.rect(screen, RED, close_button, border_radius=7)
        draw_text(screen, small_font, "CLOSE  (ESC)", (432, 446), WHITE)
    if tutorial_visible:
        overlay = pygame.Rect(105, 70, 750, 410)
        pygame.draw.rect(screen, (12, 20, 45), overlay, border_radius=14)
        pygame.draw.rect(screen, GOLD, overlay, 3, border_radius=14)
        draw_text(screen, title_font, "MULTIPLAYER GUIDE", (286, 91), GOLD)
        draw_text(screen, font, "1. Host: choose F2 HOST, then press ENTER.", (155, 175), WHITE)
        draw_text(screen, font, "2. Share your computer's IP and UDP port 50007.", (155, 215), WHITE)
        draw_text(screen, font, "3. Join: enter the host IP and port, then click CONNECT.", (155, 255), WHITE)
        draw_text(screen, font, "4. Allow UDP port 50007 through the host firewall.", (155, 295), WHITE)
        draw_text(screen, small_font, "Everyone must run the same Super Mario PC & Mobile file.", (270, 342), (170, 194, 225))
        draw_text(screen, small_font, "WASD move  |  Mouse look  |  SPACE jump  |  T chat", (250, 370), (170, 194, 225))
        close_button = pygame.Rect(405, 420, 150, 34)
        pygame.draw.rect(screen, RED, close_button, border_radius=7)
        draw_text(screen, small_font, "CLOSE  (ESC)", (432, 428), WHITE)
    if options_visible:
        overlay = pygame.Rect(155, 82, 650, 370)
        pygame.draw.rect(screen, (12, 20, 45), overlay, border_radius=14)
        pygame.draw.rect(screen, GOLD, overlay, 3, border_radius=14)
        draw_text(screen, title_font, "OPTIONS", (375, 102), GOLD)
        draw_text(screen, font, "GRAPHICS QUALITY", (205, 185), WHITE)
        quality_names = ("POTATO", "MEDIUM", "GOOD", "FANCY", "FABULOUS")
        for index, quality_name in enumerate(quality_names):
            box = pygame.Rect(205 + index * 106, 225, 94, 38)
            selected = graphics_quality == index
            pygame.draw.rect(screen, (72, 61, 52) if selected else (27, 45, 84), box, border_radius=6)
            pygame.draw.rect(screen, GOLD if selected else (67, 95, 140), box, 2, border_radius=6)
            draw_text(screen, small_font, quality_name, (box.x + 10, box.y + 11), WHITE if selected else (181, 198, 225))
        quality_help = ("Flat sky, simple surfaces, best speed",
                        "Coarse textures, fewer details",
                        "Full textures and shadows",
                        "Sharper ground and richer sky",
                        "Finest ground detail and scenery")
        draw_text(screen, small_font, quality_help[max(0, min(4, graphics_quality))], (205, 269), (181, 198, 225))
        draw_text(screen, font, "CAMERA MODE", (205, 295), WHITE)
        first_box = pygame.Rect(205, 335, 180, 40)
        third_box = pygame.Rect(420, 335, 180, 40)
        for box, label, selected in ((first_box, "FIRST PERSON", view_mode == "first"), (third_box, "THIRD PERSON", view_mode == "third")):
            pygame.draw.rect(screen, (72, 61, 52) if selected else (27, 45, 84), box, border_radius=6)
            pygame.draw.rect(screen, GOLD if selected else (67, 95, 140), box, 2, border_radius=6)
            draw_text(screen, small_font, label, (box.x + 28, box.y + 12), WHITE if selected else (181, 198, 225))
        draw_text(screen, font, "CONTROL SCHEME", (205, 390), WHITE)
        control_names = (("AUTO", "auto"), ("PC", "pc"), ("MOBILE", "mobile"))
        for index, (label, value) in enumerate(control_names):
            box = pygame.Rect(420 + index * 92, 382, 78, 30)
            selected = control_mode == value
            pygame.draw.rect(screen, (72, 61, 52) if selected else (27, 45, 84), box, border_radius=5)
            pygame.draw.rect(screen, GOLD if selected else (67, 95, 140), box, 2, border_radius=5)
            draw_text(screen, small_font, label, (box.x + 13, box.y + 8), WHITE if selected else (181, 198, 225))
        close_button = pygame.Rect(405, 420, 150, 28)
        pygame.draw.rect(screen, RED, close_button, border_radius=7)
        draw_text(screen, small_font, "CLOSE  (ESC)", (432, 426), WHITE)
    if join_visible:
        overlay = pygame.Rect(155, 82, 650, 370)
        pygame.draw.rect(screen, (12, 20, 45), overlay, border_radius=14)
        pygame.draw.rect(screen, GOLD, overlay, 3, border_radius=14)
        draw_text(screen, title_font, "JOIN GAME", (370, 102), GOLD)
        draw_text(screen, font, "CONNECTION", (205, 180), WHITE)
        for index, (label, value) in enumerate((("LOCAL", "local"), ("ONLINE", "online"))):
            box = pygame.Rect(205 + index * 180, 215, 160, 40)
            selected = join_kind == value
            pygame.draw.rect(screen, (72, 61, 52) if selected else (27, 45, 84), box, border_radius=6)
            pygame.draw.rect(screen, GOLD if selected else (67, 95, 140), box, 2, border_radius=6)
            draw_text(screen, font, label, (box.x + 48, box.y + 12), WHITE if selected else (181, 198, 225))
        for label, value, y, active in (("IP ADDRESS", join_ip, 285, join_focus == 0), ("PORT", join_port, 335, join_focus == 1)):
            box = pygame.Rect(205, y, 390, 38)
            pygame.draw.rect(screen, (27, 45, 84), box, border_radius=6)
            pygame.draw.rect(screen, GOLD if active else (67, 95, 140), box, 2, border_radius=6)
            draw_text(screen, small_font, label, (220, y + 11), (153, 176, 216))
            draw_text(screen, font, value, (350, y + 8), GOLD if active else WHITE)
        draw_text(screen, small_font, "Click a field or press TAB to switch; BACKSPACE erases.", (232, 377), (170, 194, 225))
        draw_text(screen, small_font, "Host must be running HOST; internet play needs UDP 50007 forwarded.", (191, 397), (170, 194, 225))
        close_button = pygame.Rect(315, 420, 130, 28)
        pygame.draw.rect(screen, RED, close_button, border_radius=7)
        draw_text(screen, small_font, "CANCEL", (354, 426), WHITE)
        connect_button = pygame.Rect(475, 420, 140, 28)
        pygame.draw.rect(screen, (37, 133, 74), connect_button, border_radius=7)
        pygame.draw.rect(screen, GOLD, connect_button, 2, border_radius=7)
        draw_text(screen, small_font, "CONNECT", (513, 426), WHITE)


def main():
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    pygame.display.set_caption("Super Mario PC & Mobile")
    pygame.display.set_icon(make_mario_icon())
    clock = pygame.time.Clock()
    title_font = pygame.font.Font(None, 70)
    font = pygame.font.Font(None, 28)
    small_font = pygame.font.Font(None, 22)
    player_name, character_style = load_profile()
    textures = make_textures(character_style)
    sounds = setup_audio()
    platforms, coin_positions, enemy_positions = make_level()
    player = Player()
    enemies = [Enemy(*enemy) for enemy in enemy_positions]
    coins = list(coin_positions)
    score = 0
    coins_collected = 0
    game_state = "menu"
    host_address = "127.0.0.1"
    world_id = 1
    menu_focus = 0
    game_mode = "solo"
    network = None
    remote_players = []
    menu_error = ""
    camera_yaw = 0.0
    camera_pitch = 0.0
    controls_visible = False
    tutorial_visible = False
    options_visible = False
    graphics_quality = 2
    view_mode = "first"
    control_mode = "auto"
    join_visible = False
    join_kind = "local"
    join_ip = "127.0.0.1"
    join_port = "50007"
    join_focus = 0
    profile_saved = False
    world_banner = ""
    world_banner_until = 0.0
    chat_input = ""
    chat_typing = False
    chat_messages = []
    paused = False
    touch_points = {}
    mobile_active = False
    running = True

    def start_selected_game():
        nonlocal network, platforms, coin_positions, remote_players, player, enemies, coins
        nonlocal menu_error, coins_collected, chat_messages, paused, world_banner, game_state, join_visible
        if not player_name.strip():
            menu_error = "Please enter a player name."
            return
        if network:
            network.close()
            network = None
        try:
            selected_port = NetworkSession.port
            remote_address = host_address.strip() or "127.0.0.1"
            if game_mode == "join":
                selected_port = int(join_port)
                if not 1 <= selected_port <= 65535 or not join_ip.strip():
                    raise ValueError
                remote_address = join_ip.strip()
            if game_mode in ("host", "join"):
                network = NetworkSession(player_name.strip(), game_mode, remote_address,
                                         selected_port if game_mode == "join" else NetworkSession.port)
            new_platforms, new_coins, enemy_positions = make_level(world_id)
            if game_mode == "test":
                enemy_positions.extend([(-3, 1.5, 10), (3, 1.5, 20), (0, 1.5, 42), (2.5, 1.5, 62)])
                remote_players = make_test_npcs()
            else:
                remote_players = []
            platforms, coin_positions = new_platforms, new_coins
            player = Player()
            enemies = [Enemy(*enemy) for enemy in enemy_positions]
            coins = list(coin_positions)
            menu_error = ""
            coins_collected = 0
            chat_messages = []
            paused = False
            world_banner = ""
            join_visible = False
            game_state = "playing"
            play_world_theme()
        except ValueError:
            menu_error = "Enter a valid host IP and port (1-65535)."
        except OSError as error:
            network = None
            menu_error = f"Network unavailable: {error}"

    while running:
        clock.tick(FPS)
        join_connect_requested = False
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            if event.type == pygame.FINGERDOWN:
                mobile_active = True
                touch_position = (event.x * SCREEN_WIDTH, event.y * SCREEN_HEIGHT)
                touch_points[event.finger_id] = touch_position
                pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": touch_position}))
            elif event.type == pygame.FINGERMOTION:
                touch_points[event.finger_id] = (event.x * SCREEN_WIDTH, event.y * SCREEN_HEIGHT)
            elif event.type == pygame.FINGERUP:
                touch_points.pop(event.finger_id, None)
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and game_state == "menu":
                if pygame.Rect(430, 24, 160, 40).collidepoint(event.pos):
                    options_visible = not options_visible
                    controls_visible = False
                    tutorial_visible = False
                elif pygame.Rect(610, 24, 160, 40).collidepoint(event.pos):
                    tutorial_visible = not tutorial_visible
                    controls_visible = False
                    options_visible = False
                elif pygame.Rect(790, 24, 130, 40).collidepoint(event.pos):
                    controls_visible = not controls_visible
                    tutorial_visible = False
                    options_visible = False
                elif controls_visible and pygame.Rect(405, 438, 150, 34).collidepoint(event.pos):
                    controls_visible = False
                elif tutorial_visible and pygame.Rect(405, 420, 150, 34).collidepoint(event.pos):
                    tutorial_visible = False
                elif options_visible and pygame.Rect(405, 420, 150, 28).collidepoint(event.pos):
                    options_visible = False
                elif join_visible and pygame.Rect(475, 420, 140, 28).collidepoint(event.pos):
                    join_connect_requested = True
                elif join_visible and pygame.Rect(315, 420, 130, 28).collidepoint(event.pos):
                    join_visible = False
                elif join_visible:
                    if pygame.Rect(205, 215, 160, 40).collidepoint(event.pos):
                        join_kind = "local"
                        join_ip = "127.0.0.1"
                    elif pygame.Rect(385, 215, 160, 40).collidepoint(event.pos):
                        join_kind = "online"
                    elif pygame.Rect(205, 285, 390, 38).collidepoint(event.pos):
                        join_focus = 0
                    elif pygame.Rect(205, 335, 390, 38).collidepoint(event.pos):
                        join_focus = 1
                elif options_visible:
                    quality_buttons = (pygame.Rect(205, 225, 94, 38), pygame.Rect(311, 225, 94, 38), pygame.Rect(417, 225, 94, 38), pygame.Rect(523, 225, 94, 38), pygame.Rect(629, 225, 94, 38))
                    for quality_index, button in enumerate(quality_buttons):
                        if button.collidepoint(event.pos):
                            graphics_quality = quality_index
                    if pygame.Rect(205, 335, 180, 40).collidepoint(event.pos):
                        view_mode = "first"
                    elif pygame.Rect(420, 335, 180, 40).collidepoint(event.pos):
                        view_mode = "third"
                    control_buttons = (pygame.Rect(420, 382, 78, 30), pygame.Rect(512, 382, 78, 30), pygame.Rect(604, 382, 78, 30))
                    for control_index, button in enumerate(control_buttons):
                        if button.collidepoint(event.pos):
                            control_mode = ("auto", "pc", "mobile")[control_index]
                elif not controls_visible and not tutorial_visible:
                    if pygame.Rect(594, 405, 291, 34).collidepoint(event.pos):
                        profile_saved = save_profile(player_name, character_style)
                    style_buttons = (pygame.Rect(170, 407, 34, 24), pygame.Rect(218, 407, 34, 24), pygame.Rect(266, 407, 34, 24))
                    for style_index, button in enumerate(style_buttons):
                        if button.collidepoint(event.pos):
                            character_style = style_index
                            textures = make_textures(character_style)
                            profile_saved = False
                    world_buttons = (pygame.Rect(170, 367, 92, 34), pygame.Rect(278, 367, 92, 34), pygame.Rect(386, 367, 92, 34))
                    for world_index, button in enumerate(world_buttons, 1):
                        if button.collidepoint(event.pos):
                            world_id = world_index
                    mode_buttons = (pygame.Rect(590, 218, 295, 34), pygame.Rect(590, 260, 295, 34), pygame.Rect(590, 302, 295, 34), pygame.Rect(590, 344, 295, 34))
                    for button_index, button in enumerate(mode_buttons):
                        if button.collidepoint(event.pos):
                            game_mode = ("solo", "host", "join", "test")[button_index]
                            if game_mode == "join":
                                join_visible = True
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and game_state == "playing":
                if pygame.Rect(430, 8, 100, 32).collidepoint(event.pos):
                    paused = not paused
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    if controls_visible:
                        controls_visible = False
                    elif tutorial_visible:
                        tutorial_visible = False
                    elif options_visible:
                        options_visible = False
                    elif join_visible:
                        join_visible = False
                    elif game_state == "playing" and chat_typing:
                        chat_typing = False
                        chat_input = ""
                    else:
                        running = False
                elif event.key == pygame.K_F11:
                    try:
                        pygame.display.toggle_fullscreen()
                    except pygame.error:
                        pass
                if game_state == "menu":
                    if event.key == pygame.K_TAB:
                        if join_visible:
                            join_focus = 1 - join_focus
                        else:
                            menu_focus = 1 - menu_focus
                    elif event.key == pygame.K_BACKSPACE:
                        if join_visible and join_focus == 0:
                            join_ip = join_ip[:-1]
                        elif join_visible and join_focus == 1:
                            join_port = join_port[:-1]
                        elif menu_focus == 0:
                            player_name = player_name[:-1]
                        else:
                            host_address = host_address[:-1]
                    elif event.key == pygame.K_F1:
                        game_mode = "solo"
                    elif event.key == pygame.K_F2:
                        game_mode = "host"
                    elif event.key == pygame.K_F3:
                        game_mode = "join"
                        join_visible = True
                    elif event.key == pygame.K_F4:
                        game_mode = "test"
                    elif event.key == pygame.K_F5:
                        tutorial_visible = not tutorial_visible
                    elif event.key == pygame.K_F6:
                        character_style = (character_style + 1) % 3
                        textures = make_textures(character_style)
                        profile_saved = False
                    elif event.key == pygame.K_F7:
                        profile_saved = save_profile(player_name, character_style)
                    elif event.key == pygame.K_F8:
                        options_visible = not options_visible
                    elif event.key == pygame.K_c:
                        control_mode = ("auto", "pc", "mobile")[("auto", "pc", "mobile").index(control_mode) + 1 if control_mode != "mobile" else 0]
                    elif event.key in (pygame.K_F9, pygame.K_F10, pygame.K_F11, pygame.K_F12, pygame.K_0):
                        graphics_quality = {pygame.K_F9: 0, pygame.K_F10: 1, pygame.K_F11: 2, pygame.K_F12: 3, pygame.K_0: 4}[event.key]
                    elif event.key == pygame.K_v:
                        view_mode = "third" if view_mode == "first" else "first"
                    elif event.key in (pygame.K_1, pygame.K_2, pygame.K_3):
                        world_id = event.key - pygame.K_0
                    elif event.key == pygame.K_RETURN:
                        join_connect_requested = True
                    elif join_visible and event.key == pygame.K_TAB:
                        join_focus = 1 - join_focus
                    elif join_visible and event.key == pygame.K_BACKSPACE:
                        if join_focus == 0:
                            join_ip = join_ip[:-1]
                        else:
                            join_port = join_port[:-1]
                    elif join_visible and event.unicode and event.unicode.isprintable():
                        if join_focus == 0 and len(join_ip) < 45:
                            join_ip += event.unicode
                        elif join_focus == 1 and event.unicode.isdigit() and len(join_port) < 5:
                            join_port += event.unicode
                    elif event.unicode and event.unicode.isprintable():
                        if menu_focus == 0 and len(player_name) < 16:
                            player_name += event.unicode
                            profile_saved = False
                        elif menu_focus == 1 and len(host_address) < 40:
                            host_address += event.unicode
                elif game_state == "playing":
                    if event.key == pygame.K_p and not chat_typing:
                        paused = not paused
                    elif event.key == pygame.K_t and not chat_typing:
                        chat_typing = True
                        pygame.key.start_text_input()
                    elif chat_typing and event.key == pygame.K_BACKSPACE:
                        chat_input = chat_input[:-1]
                    elif chat_typing and event.key == pygame.K_RETURN:
                        message_text = chat_input.strip()
                        if message_text:
                            chat_messages.append({
                                "id": network.player_id if network else "local",
                                "name": player_name,
                                "text": message_text,
                                "expires": time.monotonic() + 5,
                            })
                            if network:
                                network.send_chat(message_text)
                        chat_input = ""
                        chat_typing = False
                        pygame.key.stop_text_input()
                    elif chat_typing and event.unicode and event.unicode.isprintable() and len(chat_input) < 80:
                        chat_input += event.unicode
                elif event.key in (pygame.K_RETURN, pygame.K_SPACE) and game_state in ("gameover", "win"):
                    if network:
                        network.close()
                        network = None
                    game_state = "menu"
                    platforms, coin_positions, enemy_positions = make_level(world_id)
                    player = Player()
                    enemies = [Enemy(*enemy) for enemy in enemy_positions]
                    coins = list(coin_positions)
                    score = 0
                    coins_collected = 0
                    chat_messages = []
                    paused = False
                    world_banner = ""

        if join_connect_requested and game_state == "menu":
            start_selected_game()

        if game_state == "playing" and not paused:
            use_touch = control_mode == "mobile" or (control_mode == "auto" and mobile_active)
            keys = TouchInput(touch_points) if use_touch else pygame.key.get_pressed()
            if keys[pygame.K_q]:
                camera_yaw -= 0.035
            if keys[pygame.K_e]:
                camera_yaw += 0.035
            if keys[pygame.K_r]:
                camera_pitch += 0.025
            if keys[pygame.K_f]:
                camera_pitch -= 0.025
            mouse_delta_x, mouse_delta_y = pygame.mouse.get_rel()
            camera_yaw += mouse_delta_x * 0.0025
            camera_pitch = max(-0.45, min(0.45, camera_pitch - mouse_delta_y * 0.0025))
            player.update(keys, platforms, sounds, camera_yaw)
            now = time.monotonic()
            chat_messages = [message for message in chat_messages if message["expires"] > now]
            for enemy in enemies:
                enemy.update(platforms)
            for coin in coins[:]:
                if math.dist((player.x, player.y, player.z), coin) < 1.1:
                    coins.remove(coin)
                    score += 100
                    coins_collected += 1
                    if "coin" in sounds:
                        sounds["coin"].play()
            for enemy in enemies[:]:
                if enemy.overlaps_player(player):
                    if player.velocity_y < 0 and enemy.y + 0.45 < player.y < enemy.y + 1.25:
                        enemies.remove(enemy)
                        player.velocity_y = 0.2
                        score += 250
                        if "stomp" in sounds:
                            sounds["stomp"].play()
                    else:
                        player.lives -= 1
                        if "hurt" in sounds:
                            sounds["hurt"].play()
                        player.respawn()
                        if player.lives <= 0:
                            game_state = "gameover"
            if player.y < -2 or player.z < 0:
                player.lives -= 1
                if "hurt" in sounds:
                    sounds["hurt"].play()
                player.respawn()
                if player.lives <= 0:
                    game_state = "gameover"
            if player.z >= WORLD_END - 4:
                if world_id < 3:
                    world_id += 1
                    platforms, coin_positions, enemy_positions = make_level(world_id)
                    if game_mode == "test":
                        enemy_positions.extend([(-3, 1.5, 10), (3, 1.5, 20), (0, 1.5, 42), (2.5, 1.5, 62)])
                    enemies = [Enemy(*enemy) for enemy in enemy_positions]
                    coins = list(coin_positions)
                    player.respawn()
                    remote_players = make_test_npcs() if game_mode == "test" else remote_players
                    world_banner = f"WORLD {world_id}"
                    world_banner_until = time.monotonic() + 2.5
                else:
                    game_state = "win"

        if game_state == "playing":
            if network:
                remote_players = network.update(player.x, player.y, player.z)
                for message in network.drain_chat():
                    if message.get("id") != network.player_id:
                        message["expires"] = time.monotonic() + 5
                        chat_messages.append(message)
            elif game_mode == "test" and not paused:
                update_test_npcs(remote_players)

        if game_state == "playing" and not paused:
            pygame.mouse.set_visible(False)
            pygame.event.set_grab(True)
            if view_mode == "first":
                camera = (player.x, player.y + 1.25, player.z - 0.3, camera_yaw, camera_pitch)
            else:
                camera = third_person_camera(player, camera_yaw, camera_pitch)
        elif game_state == "playing":
            pygame.mouse.set_visible(True)
            pygame.event.set_grab(False)
            pygame.mouse.get_rel()
            if view_mode == "first":
                camera = (player.x, player.y + 1.25, player.z - 0.3, camera_yaw, camera_pitch)
            else:
                camera = third_person_camera(player, camera_yaw, camera_pitch)
        else:
            pygame.mouse.set_visible(True)
            pygame.event.set_grab(False)
            pygame.mouse.get_rel()
            camera = (player.x * 0.45, 3.4 + max(0, player.y - 1.5) * 0.25, player.z - 8.5)
        draw_background(screen, camera, graphics_quality)
        draw_world(screen, camera, platforms, coins, enemies, WORLD_END, textures, graphics_quality)
        for enemy in enemies:
            enemy.draw(screen, camera, textures, graphics_quality)
        for remote_player in remote_players:
            draw_remote_player(screen, camera, remote_player, textures, small_font, graphics_quality)
        if game_state == "playing" and view_mode == "first":
            draw_first_person_hands(screen, camera, textures, graphics_quality)
        elif game_state != "playing" or view_mode == "third":
            player.draw(screen, camera, textures, graphics_quality)
        if game_state == "playing" and (control_mode == "mobile" or (control_mode == "auto" and mobile_active)) and not paused:
            draw_touch_controls(screen)
        if game_state == "menu":
            draw_menu(screen, title_font, font, small_font, player_name, host_address, game_mode, menu_focus, menu_error, world_id, character_style, controls_visible, tutorial_visible, profile_saved, options_visible, graphics_quality, view_mode, control_mode, join_visible, join_kind, join_ip, join_port, join_focus)
        else:
            pygame.draw.rect(screen, (18, 25, 53), (0, 0, SCREEN_WIDTH, 48))
            draw_text(screen, font, f"SCORE {score:05d}", (22, 13), GOLD)
            draw_text(screen, font, f"LIVES {player.lives}", (205, 13))
            draw_text(screen, font, f"COINS {coins_collected:02d}", (300, 13), GOLD)
            draw_text(screen, small_font, f"{player_name}  |  PLAYERS: {len(remote_players) + 1}", (440, 16), (207, 220, 255))
            if network:
                connection_status = network.status()
                status_color = (105, 235, 140) if connection_status == "CONNECTED" else (255, 210, 100)
                draw_text(screen, small_font, connection_status, (720, 16), status_color)
            pause_button = pygame.Rect(430, 8, 100, 32)
            pygame.draw.rect(screen, GOLD if paused else (50, 72, 112), pause_button, border_radius=7)
            pygame.draw.rect(screen, GOLD, pause_button, 2, border_radius=7)
            pause_label = "RESUME" if paused else "PAUSE"
            draw_text(screen, small_font, pause_label, (452 if paused else 457, 16), INK if paused else GOLD)
            if game_state == "playing":
                for remote_player in remote_players:
                    draw_nameplate(screen, camera, remote_player["x"], remote_player["y"], remote_player["z"], remote_player["name"], small_font)
                draw_leaderboard(screen, small_font, player_name, player.z, remote_players)
                for message in chat_messages:
                    if message["id"] == (network.player_id if network else "local"):
                        bubble_x, bubble_y, bubble_z = player.x, player.y, player.z
                    else:
                        matching_player = next((item for item in remote_players if item["id"] == message["id"]), None)
                        if not matching_player:
                            continue
                        bubble_x, bubble_y, bubble_z = matching_player["x"], matching_player["y"], matching_player["z"]
                    draw_chat_bubble(screen, camera, bubble_x, bubble_y, bubble_z, message["text"], small_font)
                if chat_typing:
                    chat_box = pygame.Rect(18, SCREEN_HEIGHT - 58, 520, 38)
                    pygame.draw.rect(screen, (18, 25, 53), chat_box, border_radius=7)
                    pygame.draw.rect(screen, GOLD, chat_box, 2, border_radius=7)
                    draw_text(screen, small_font, f"CHAT: {chat_input}_", (30, SCREEN_HEIGHT - 49), WHITE)
                else:
                    draw_text(screen, small_font, "T: CHAT", (24, SCREEN_HEIGHT - 30), (207, 220, 255))
            if world_banner and time.monotonic() < world_banner_until:
                banner = font.render(f"{world_banner} START!", True, GOLD)
                screen.blit(banner, (SCREEN_WIDTH // 2 - banner.get_width() // 2, 74))
            if paused:
                pause_overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
                pause_overlay.fill((8, 13, 31, 100))
                screen.blit(pause_overlay, (0, 0))
                draw_text(screen, title_font, "PAUSED", (405, 210), GOLD)
                draw_text(screen, font, "Click RESUME or press P", (362, 290), WHITE)
        if game_state in ("gameover", "win"):
            pygame.draw.rect(screen, (20, 29, 61), (220, 175, 520, 185))
            heading = "YOU WIN!" if game_state == "win" else "GAME OVER"
            draw_text(screen, title_font, heading, (335, 205), GOLD if game_state == "win" else RED)
            draw_text(screen, font, f"FINAL SCORE: {score:05d}", (370, 280))
            draw_text(screen, font, "PRESS ENTER TO PLAY AGAIN", (310, 320))
        pygame.display.flip()

    if network:
        network.close()
    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
