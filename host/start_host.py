"""Start the Tessera USB host without opening the editor."""
from deck_control import Controller


def main():
    Controller().start()


if __name__ == '__main__':
    main()
