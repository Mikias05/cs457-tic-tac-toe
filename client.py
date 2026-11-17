import argparse
import json
import select
import socket
import sys


def check_port(value):
    port = int(value)

    if port < 1024 or port > 65535:
        raise argparse.ArgumentTypeError(
            "port must be between 1024 and 65535"
        )

    return port


def print_board(board):
    spots = []

    for index, value in enumerate(board):
        if value == " ":
            spots.append(str(index + 1))
        else:
            spots.append(value)

    print()
    print(f" {spots[0]} | {spots[1]} | {spots[2]} ")
    print("---+---+---")
    print(f" {spots[3]} | {spots[4]} | {spots[5]} ")
    print("---+---+---")
    print(f" {spots[6]} | {spots[7]} | {spots[8]} ")
    print()


class TicTacToeClient:
    def __init__(self, hostname, port):
        self.hostname = hostname
        self.port = port
        self.sock = None

        self.player_mark = None
        self.board = [" "] * 9
        self.current_turn = None

        self.game_started = False
        self.game_finished = False
        self.incoming_text = ""

    def connect_to_game(self):
        try:
            server_ip = socket.gethostbyname(self.hostname)
        except socket.gaierror:
            print(
                f"[ERROR] Unable to resolve DNS hostname "
                f"'{self.hostname}'."
            )
            print(
                "Please check your Cisco router DNS configuration "
                "('ip dns server' / 'ip host') or verify the hostname."
            )
            return False

        self.sock = socket.socket(
            socket.AF_INET,
            socket.SOCK_STREAM
        )

        try:
            self.sock.connect((server_ip, self.port))
        except OSError as error:
            print(
                f"[ERROR] Could not connect to "
                f"{self.hostname}:{self.port}."
            )
            print(error)
            self.sock.close()
            return False

        print(
            f"Connected to {self.hostname} "
            f"({server_ip}) on port {self.port}."
        )

        return True

    def run_game(self):
        while True:
            try:
                ready, _, _ = select.select(
                    [self.sock, sys.stdin],
                    [],
                    []
                )
            except KeyboardInterrupt:
                print("\nLeaving game.")
                break

            if self.sock in ready:
                if not self.read_server_messages():
                    break

            if sys.stdin in ready:
                typed = sys.stdin.readline()

                if typed == "":
                    break

                self.use_keyboard_input(typed.strip())

        self.sock.close()

    def read_server_messages(self):
        try:
            data = self.sock.recv(4096)
        except ConnectionError:
            print("\nConnection to server was lost.")
            return False

        if not data:
            print("\nServer closed the connection.")
            return False

        self.incoming_text += data.decode("utf-8")

        while "\n" in self.incoming_text:
            raw_message, self.incoming_text = (
                self.incoming_text.split("\n", 1)
            )

            if raw_message.strip() == "":
                continue

            try:
                message = json.loads(raw_message)
            except json.JSONDecodeError:
                print("Received an unreadable message from the server.")
                continue

            self.process_server_message(message)

        return True

    def process_server_message(self, message):
        message_type = message.get("type")

        if message_type == "CONNECT":
            self.player_mark = message.get("player")
            print(f"You are Player {self.player_mark}.")

        elif message_type == "LOBBY_WAIT":
            print("Waiting for Player 2...")

        elif message_type == "GAME_START":
            self.game_started = True
            self.game_finished = False
            self.board = message.get("board", self.board)
            self.current_turn = message.get("turn")

            print("\nBoth players connected. Game starting.")
            print_board(self.board)
            self.show_turn_status()

        elif message_type == "STATE_UPDATE":
            self.board = message.get("board", self.board)
            self.current_turn = message.get("turn")
            scores = message.get("scores", {})

            print_board(self.board)

            print(
                f"Score - X: {scores.get('X', 0)} "
                f"O: {scores.get('O', 0)}"
            )

            self.show_turn_status()

        elif message_type == "GAME_OVER":
            self.board = message.get("board", self.board)
            scores = message.get("scores", {})
            winner = message.get("winner")

            self.game_finished = True

            print_board(self.board)

            if winner is None:
                print("Game Over - Draw.")
            elif winner == self.player_mark:
                print("Game Over - You won!")
            else:
                print(f"Game Over - Player {winner} won.")

            print(
                f"Final Score - X: {scores.get('X', 0)} "
                f"O: {scores.get('O', 0)}"
            )

        elif message_type == "ERROR":
            print(f"Server error: {message.get('message')}")
            self.show_turn_status()

    def use_keyboard_input(self, typed):
        if not self.game_started:
            print("Waiting for the game to start.")
            return

        if self.game_finished:
            print("This round is finished.")
            return

        if self.current_turn != self.player_mark:
            print(f"Waiting for Player {self.current_turn}...")
            return

        try:
            position = int(typed)
        except ValueError:
            print("Enter a position from 1 through 9.")
            self.show_turn_status()
            return

        if position < 1 or position > 9:
            print("Enter a position from 1 through 9.")
            self.show_turn_status()
            return

        self.send_move(position)

    def send_move(self, position):
        message = {
            "type": "MOVE",
            "position": position
        }

        wire_message = json.dumps(message) + "\n"

        try:
            self.sock.sendall(wire_message.encode("utf-8"))
        except ConnectionError:
            print("Could not send move to the server.")

    def show_turn_status(self):
        if not self.game_started or self.game_finished:
            return

        if self.current_turn == self.player_mark:
            print("Your Turn - enter a position from 1 to 9:")
        else:
            print(f"Waiting for Player {self.current_turn}...")


def main():
    parser = argparse.ArgumentParser(
        description="Tic-Tac-Toe multiplayer client"
    )

    parser.add_argument(
        "-i",
        "--hostname",
        required=True,
        help="server DNS hostname or IP address"
    )

    parser.add_argument(
        "-p",
        "--port",
        required=True,
        type=check_port,
        help="server TCP port"
    )

    args = parser.parse_args()

    game_client = TicTacToeClient(
        args.hostname,
        args.port
    )

    if not game_client.connect_to_game():
        sys.exit(1)

    try:
        game_client.run_game()
    except KeyboardInterrupt:
        print("\nClient closed.")


if __name__ == "__main__":
    main()
