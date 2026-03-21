import serial
import time
import argparse

def main():
    parser = argparse.ArgumentParser(description="Test raw serial data from the scale.")
    parser.add_argument("--port", type=str, default="COM4", help="Serial port (e.g., COM4, /dev/ttyUSB0)")
    parser.add_argument("--baud", type=int, default=9600, help="Baud rate (default: 9600)")
    args = parser.parse_args()

    print(f"Connecting to scale on {args.port} at {args.baud} baud...")

    try:
        ser = serial.Serial(
            port=args.port,
            baudrate=args.baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=1
        )
        print("Connected! Reading data... (Press Ctrl+C to stop)")
        
        while True:
            if ser.in_waiting > 0:
                raw_data = ser.readline()
                try:
                    text_data = raw_data.decode('utf-8', errors='ignore').replace('\r', '').replace('\n', '')
                    print(f"RAW BINARY: {raw_data}  ->  TEXT: '{text_data}'")
                except Exception as e:
                    print(f"RAW BINARY: {raw_data}  ->  Error decoding: {e}")
            time.sleep(0.05)

    except serial.SerialException as e:
        print(f"Failed to connect to the serial port: {e}")
    except KeyboardInterrupt:
        print("\nStopped manually.")
    finally:
        if 'ser' in locals() and ser.is_open:
            ser.close()
            print("Serial port closed.")

if __name__ == "__main__":
    main()
