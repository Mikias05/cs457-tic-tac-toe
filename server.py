import argparse
import json
import selectors
import socket


def check_port(value):
    value = int(value)

    if value < 1024 or value > 65535:
        raise argparse.ArgumentTypeError("port must be between 1024 and 65535")

    return value


class PlayerConnection:
    def __init__(self, sock, address):
        self.sock = sock
        self.address = address
        self.mark = None
        self.read_buffer = ""
        self.send_buffer = bytearray()


class TicTacToeServer:
    def __init__(self, port):
        self.port = port
        self.selector = selectors.DefaultSelector()

        self.connections = {}
        self.player_x = None
        self.player_o = None

        self.board = [" "] * 9
        self.whose_turn = "X"
        self.round_finished = False

        self.score = {
            "X": 0,
            "O": 0
        }

    def run(self):
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        server_socket.bind(("0.0.0.0", self.port))
        server_socket.listen()
        server_socket.setblocking(False)

        self.selector.register(
            server_socket,
            selectors.EVENT_READ,
            data=None
        )

        print(f"Tic-Tac-Toe server listening on port {self.port}")

        while True:
            ready = self.selector.select()

            for key, mask in ready:
                if key.data is None:
                    self.accept_player(server_socket)
                    continue

                player = key.data

                if mask & selectors.EVENT_READ:
                    if not self.read_from_player(player):
                        continue

                if mask & selectors.EVENT_WRITE:
                    self.flush_player_output(player)

    def accept_player(self, server_socket):
        sock, address = server_socket.accept()
        sock.setblocking(False)

        player = PlayerConnection(sock, address)
        self.connections[sock] = player

        self.selector.register(
            sock,
            selectors.EVENT_READ,
            data=player
        )

        print(f"New connection: {address}")

        if self.player_x is None:
            player.mark = "X"
            self.player_x = player

        elif self.player_o is None:
            player.mark = "O"
            self.player_o = player

        else:
            self.send_json(player, {
                "type": "ERROR",
                "message": "Two players are already connected."
            })
            return

        self.send_json(player, {
            "type": "CONNECT",
            "player": player.mark
        })

        if self.player_x is not None and self.player_o is not None:
            self.send_to_both({
                "type": "GAME_START",
                "board": self.board,
                "turn": self.whose_turn,
                "scores": self.score
            })
        else:
            self.send_json(player, {
                "type": "LOBBY_WAIT",
                "message": "Waiting for the second player..."
            })

    def read_from_player(self, player):
        try:
            incoming = player.sock.recv(4096)
        except ConnectionError:
            self.remove_player(player)
            return False

        if not incoming:
            self.remove_player(player)
            return False

        player.read_buffer += incoming.decode("utf-8")

        while "\n" in player.read_buffer:
            raw, player.read_buffer = player.read_buffer.split("\n", 1)

            if raw.strip() == "":
                continue

            try:
                request = json.loads(raw)
            except json.JSONDecodeError:
                self.send_json(player, {
                    "type": "ERROR",
                    "message": "Could not read message."
                })
                continue

            if request.get("type") == "MOVE":
                self.process_move(player, request)
            else:
                self.send_json(player, {
                    "type": "ERROR",
                    "message": "Unsupported request."
                })

        self.refresh_socket_events(player)
        return True

    def process_move(self, player, request):
        if self.player_x is None or self.player_o is None:
            self.send_json(player, {
                "type": "ERROR",
                "message": "Waiting for both players."
            })
            return

        if self.round_finished:
            self.send_json(player, {
                "type": "ERROR",
                "message": "This round is already finished."
            })
            return

        if player.mark != self.whose_turn:
            self.send_json(player, {
                "type": "ERROR",
                "message": "Not your turn."
            })
            return

        try:
            chosen_spot = int(request["position"])
        except (KeyError, TypeError, ValueError):
            self.send_json(player, {
                "type": "ERROR",
                "message": "Move must be a number from 1 through 9."
            })
            return

        if chosen_spot < 1 or chosen_spot > 9:
            self.send_json(player, {
                "type": "ERROR",
                "message": "Move must be between 1 and 9."
            })
            return

        board_index = chosen_spot - 1

        if self.board[board_index] != " ":
            self.send_json(player, {
                "type": "ERROR",
                "message": "That space is already taken."
            })
            return

        self.board[board_index] = player.mark

        winner = self.find_winner()

        if winner is not None:
            self.round_finished = True
            self.score[winner] += 1

 

            self.send_to_both({
                "type": "GAME_OVER",
                "winner": winner,
                "board": self.board,
                "scores": self.score
            })

            return

        if " " not in self.board:
            self.round_finished = True



            self.send_to_both({
                "type": "GAME_OVER",
                "winner": None,
                "board": self.board,
                "scores": self.score
            })

            return

        if self.whose_turn == "X":
            self.whose_turn = "O"
        else:
            self.whose_turn = "X"

        self.send_to_both({
            "type": "STATE_UPDATE",
            "board": self.board,
            "turn": self.whose_turn,
            "scores": self.score
        })

    def find_winner(self):
        win_sets = [
            (0, 1, 2),
            (3, 4, 5),
            (6, 7, 8),
            (0, 3, 6),
            (1, 4, 7),
            (2, 5, 8),
            (0, 4, 8),
            (2, 4, 6)
        ]

        for first, second, third in win_sets:
            mark = self.board[first]

            if mark == " ":
                continue

            if mark == self.board[second] and mark == self.board[third]:
                return mark

        return None

    def send_json(self, player, message):
        wire_message = json.dumps(message) + "\n"
        player.send_buffer.extend(wire_message.encode("utf-8"))
        self.refresh_socket_events(player)

    def send_to_both(self, message):
        if self.player_x is not None:
            self.send_json(self.player_x, message)

        if self.player_o is not None:
            self.send_json(self.player_o, message)

    def flush_player_output(self, player):
        if len(player.send_buffer) == 0:
            self.refresh_socket_events(player)
            return

        try:
            bytes_sent = player.sock.send(player.send_buffer)
            del player.send_buffer[:bytes_sent]
        except ConnectionError:
            self.remove_player(player)
            return

        self.refresh_socket_events(player)

    def refresh_socket_events(self, player):
        events = selectors.EVENT_READ

        if player.send_buffer:
            events |= selectors.EVENT_WRITE

        try:
            self.selector.modify(
                player.sock,
                events,
                data=player
            )
        except KeyError:
            pass

    def remove_player(self, player):
        print(f"Player disconnected: {player.address}")

        if self.player_x is player:
            self.player_x = None

        if self.player_o is player:
            self.player_o = None

        try:
            self.selector.unregister(player.sock)
        except Exception:
            pass

        self.connections.pop(player.sock, None)
        player.sock.close()

        self.board = [" "] * 9
        self.whose_turn = "X"
        self.round_finished = False


def main():
    parser = argparse.ArgumentParser(
        description="Tic-Tac-Toe multiplayer server"
    )

    parser.add_argument(
        "-p",
        "--port",
        required=True,
        type=check_port,
        help="TCP port to listen on"
    )

    args = parser.parse_args()

    game_server = TicTacToeServer(args.port)

    try:
        game_server.run()
    except KeyboardInterrupt:
        print("\nServer closed.")


if __name__ == "__main__":
    main()
