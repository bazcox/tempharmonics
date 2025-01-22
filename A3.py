import serial
import time
import pygame
import threading
import sys
import signal
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas
import matplotlib.pyplot as plt
import queue
from queue import Queue

"""
    CSC 413 - Assignemnt 3
    Created by Ryan Dreher
"""

# Initialize pygame mixer for sound playback
pygame.mixer.init()
# Define the serial port and baud rate.
serial_port = '/dev/cu.usbmodem1101'  # Update to match your Arduino's port
baud_rate = 115200

# Initialize global variables
current_temperature = 0.0
current_sound_file = ''
temperature_log = []
start_time = None  # Changed from time.time() to None
first_reading_received = False  # Add this line

# Create a lock for thread-safe operations
lock = threading.Lock()

# Add running flag for graceful shutdown
running = True

# Temperature zone configuration
# Zones must be ordered from coldest to hottest
TEMP_ZONES = [
    {"name": "Key 1",  "threshold": 8,  "sound_file": "key01.mp3",  "color": "#ffb3b3",  "linestyle": ":"},
    {"name": "Key 2",  "threshold": 10,  "sound_file": "key02.mp3",  "color": "#ff9999",  "linestyle": "--"},
    {"name": "Key 3",  "threshold": 12,  "sound_file": "key03.mp3",  "color": "#ff8080",  "linestyle": "-."},
    {"name": "Key 4",  "threshold": 15,  "sound_file": "key04.mp3",  "color": "#ff6666",  "linestyle": "-"},
    {"name": "Key 5",  "threshold": 17,  "sound_file": "key05.mp3",  "color": "#ff4d4d",  "linestyle": ":"},
    {"name": "Key 6",  "threshold": 19,  "sound_file": "key06.mp3",  "color": "#ff3333",  "linestyle": "--"},
    {"name": "Key 7",  "threshold": 21,  "sound_file": "key07.mp3",  "color": "#ff1a1a",  "linestyle": "-."},
    {"name": "Key 8",  "threshold": 23,  "sound_file": "key08.mp3",  "color": "#ff0000",  "linestyle": "-"},
    {"name": "Key 9",  "threshold": 25,  "sound_file": "key09.mp3",  "color": "#e60000",  "linestyle": ":"},
    {"name": "Key 10", "threshold": 28,  "sound_file": "key10.mp3",  "color": "#cc0000",  "linestyle": "--"},
    {"name": "Key 11", "threshold": 30,  "sound_file": "key11.mp3",  "color": "#b30000",  "linestyle": "-."},
    {"name": "Key 12", "threshold": 32,  "sound_file": "key12.mp3",  "color": "#990000",  "linestyle": "-"},
    {"name": "Key 13", "threshold": 38,  "sound_file": "key13.mp3",  "color": "#800000",  "linestyle": ":"},
    {"name": "Key 14", "threshold": 42,  "sound_file": "key14.mp3",  "color": "#660000",  "linestyle": "--"},
    {"name": "Key 15", "threshold": 50,  "sound_file": "key15.mp3",  "color": "#4d0000",  "linestyle": "-."},
]

def validate_temp_zones():
    """
    Validates the temperature zones defined in the global variable TEMP_ZONES.
    This function checks the following:
    1. There are at least 2 temperature zones defined.
    2. Each temperature zone contains the required keys: "name", "threshold", "sound_file", and "color".
    3. The thresholds of the temperature zones are strictly increasing.
    Raises:
        ValueError: If there are fewer than 2 temperature zones.
        ValueError: If any temperature zone is missing required keys.
        ValueError: If the thresholds of the temperature zones are not strictly increasing.
    """
    if len(TEMP_ZONES) < 2:
        raise ValueError("Must define at least 2 temperature zones")
    
    prev_threshold = float('-inf')
    for zone in TEMP_ZONES:
        if not all(key in zone for key in ["name", "threshold", "sound_file", "color"]):
            raise ValueError(f"Zone {zone} missing required keys")
        if zone["threshold"] <= prev_threshold:
            raise ValueError(f"Zone thresholds must be strictly increasing")
        prev_threshold = zone["threshold"]

def get_zone_for_temperature(temperature):
    """
    Determines the temperature zone for a given temperature.
    Args:
        temperature (float): The temperature value to classify.
    Returns:
        dict: The temperature zone dictionary that the given temperature falls into.
              Each zone dictionary contains at least a "threshold" key.
    """
    for zone in TEMP_ZONES:
        if temperature < zone["threshold"]:
            return zone
    return TEMP_ZONES[-1]  # Return last zone if no threshold is met

def signal_handler(signum, frame):
    global running
    print("\nCtrl+C detected. Cleaning up...")
    running = False

# Add these constants after the existing globals
SERIAL_TIMEOUT = 0.1  # Serial timeout in seconds
READ_INTERVAL = 0.5  # Match Arduino's 500ms interval
BUFFER_SIZE = 2048   # Increased for higher baud rate
DATA_QUEUE_SIZE = 1000
update_event = threading.Event()
data_queue = Queue(maxsize=DATA_QUEUE_SIZE)

def process_serial_data(data):
    """
    Process and validate serial data.
    Returns tuple (is_valid, temperature)
    """
    try:
        temp = float(data.strip())
        if 0 <= temp <= 100:  # Basic temperature range validation
            return True, temp
        return False, None
    except (ValueError, TypeError):
        return False, None

class TempMonitor:
    def __init__(self):
        self.current_temperature = 0.0
        self.current_sound_file = ''
        self.temperature_log = []
        self.start_time = None
        self.first_reading_received = False
        self.lock = threading.Lock()
        self.running = True
        self.data_queue = Queue(maxsize=DATA_QUEUE_SIZE)
        self.update_event = threading.Event()
        self.cached_graph = None
        self.graph_needs_update = True
        self.data_gathering = True  # Add this line
        self.stop_time = None  # Add this line

    def play_sound(self, temperature):
        """
        Plays a sound based on the given temperature.
        """
        if not self.first_reading_received:
            return
        
        zone = get_zone_for_temperature(temperature)
        sound_file = zone["sound_file"]
        self.current_sound_file = sound_file

        def play():
            try:
                sound = pygame.mixer.Sound(sound_file)
                sound.play()
                time.sleep(sound.get_length())
            except pygame.error as e:
                print(f"Error playing sound: {e}")

        threading.Thread(target=play).start()

    def process_temperature_data(self):
        while self.running and self.data_gathering:
            try:
                temperature = self.data_queue.get(timeout=0.1)
                current_time = time.time()
                with self.lock:
                    self.current_temperature = temperature
                    if not self.first_reading_received:
                        self.first_reading_received = True
                        self.start_time = current_time
                        self.temperature_log = [(0, temperature)]
                    else:
                        elapsed = current_time - self.start_time
                        self.temperature_log.append((elapsed, temperature))
                    self.graph_needs_update = True
                
                with open('temp_log.txt', 'a') as log_file:
                    log_file.write(f"{time.time()},{temperature}\n")
                
                self.play_sound(temperature)  # Updated to use instance method
                self.update_event.set()
                
            except queue.Empty:
                continue
            except Exception as e:
                print(f"Error processing temperature: {e}")

    def read_serial(self):
        ser = None
        buffer = ""
        last_read_time = 0

        try:
            ser = serial.Serial(
                port=serial_port,
                baudrate=baud_rate,
                timeout=SERIAL_TIMEOUT,
                writeTimeout=0
            )
            ser.reset_input_buffer()
            
            while self.running and self.data_gathering:
                current_time = time.time()
                if current_time - last_read_time < READ_INTERVAL:
                    time.sleep(0.001)
                    continue
                
                last_read_time = current_time
                
                if ser.in_waiting:
                    try:
                        chunk = ser.read(min(ser.in_waiting, BUFFER_SIZE)).decode('utf-8')
                        buffer += chunk
                        
                        while '\n' in buffer:
                            line, buffer = buffer.split('\n', 1)
                            is_valid, temperature = process_serial_data(line)
                            
                            if is_valid:
                                # Use non-blocking put to avoid deadlocks
                                try:
                                    self.data_queue.put(temperature, block=False)
                                except queue.Full:
                                    print("Warning: Data queue full, dropping measurement")
                                
                    except (UnicodeDecodeError, serial.SerialException) as e:
                        print(f"Error reading serial data: {e}")
                        buffer = ""
                        time.sleep(0.1)
                        
                if len(buffer) > BUFFER_SIZE:
                    buffer = buffer[-BUFFER_SIZE:]
                        
        finally:
            if ser and ser.is_open:
                ser.close()

    def draw_graph(self, screen):
        if self.graph_needs_update:
            fig = Figure(figsize=(12, 4), dpi=100)  # Increased width to 12 inches
            ax = fig.add_subplot(111)
            
            with self.lock:
                if self.temperature_log:
                    lines = []
                    labels = []

                    # Split time and temperature data
                    times, temps = zip(*self.temperature_log)
                    temp_line = ax.plot(times, temps, 'b-', zorder=10)[0]
                    lines.append(temp_line)
                    labels.append('Temperature (°C)')
                    
                    for zone in reversed(TEMP_ZONES[:]):
                        line = ax.axhline(
                            y=zone["threshold"],
                            color=zone["color"],
                            alpha=0.3,
                            linestyle=zone["linestyle"]
                        )
                        lines.append(line)
                        labels.append(f'{zone["name"]} Threshold')
                    
                    # Move legend outside of the graph and set transparent background
                    legend = ax.legend(lines, labels, loc='center left', bbox_to_anchor=(1, 0.5))
                    legend.get_frame().set_alpha(0.0)

            ax.set_xlabel('Time (seconds)')
            ax.set_ylabel('Temperature (°C)')
            ax.set_title('Temperature Over Time')
            
            ax.yaxis.set_major_formatter(plt.FormatStrFormatter('%.2f'))
            
            fig.tight_layout(rect=[0, 0, 0.85, 1])
            
            canvas = FigureCanvas(fig)
            canvas.draw()
            raw_data = bytes(canvas.get_renderer().buffer_rgba())
            size = canvas.get_width_height()
            self.cached_graph = pygame.image.fromstring(raw_data, size, "RGBA")
            plt.close(fig)
            self.graph_needs_update = False
        
        if self.cached_graph:
            screen.blit(self.cached_graph, (20, 140))

    def ui_thread(self):
        pygame.init()
        screen = pygame.display.set_mode((1100, 600))
        pygame.display.set_caption('Temp Harmonics')
        font = pygame.font.Font(None, 36)
        clock = pygame.time.Clock()
        button = pygame.Rect(900, 20, 100, 30)
        
        # Define button colors
        LIGHT_RED = (255, 102, 102)
        DARK_RED = (204, 0, 0)

        while self.running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                    break
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    mouse_pos = event.pos
                    if button.collidepoint(mouse_pos):
                        if self.data_gathering:
                            self.data_gathering = False  # Stop data gathering
                        else:
                            self.running = False  # Exit program
                        break

            screen.fill((255, 255, 255))

            # Update button color and text based on state
            button_color = LIGHT_RED if self.data_gathering else DARK_RED
            button_text = 'End' if self.data_gathering else 'Close'
            
            pygame.draw.rect(screen, button_color, button)
            end_text = font.render(button_text, True, (255, 255, 255))
            text_rect = end_text.get_rect(center=button.center)
            screen.blit(end_text, text_rect)

            with self.lock:
                temp_text = f"Temperature: {self.current_temperature:.2f} °C"
                sound_text = f"Current Sound: {self.current_sound_file}"
                if self.first_reading_received and self.start_time is not None:
                    if not self.data_gathering and self.stop_time is None:
                        self.stop_time = time.time()
                    current_time = self.stop_time if self.stop_time else time.time()
                    elapsed_time = current_time - self.start_time
                    time_text = f"Time Elapsed: {elapsed_time:.2f}s"  # Changed from int() to .2f
                else:
                    time_text = "Waiting for first reading..."

            temp_surface = font.render(temp_text, True, (0, 0, 0))
            sound_surface = font.render(sound_text, True, (0, 0, 0))
            time_surface = font.render(time_text, True, (0, 0, 0))

            screen.blit(sound_surface, (20, 20))
            screen.blit(temp_surface, (20, 60))
            screen.blit(time_surface, (20, 100))

            self.draw_graph(screen)

            pygame.display.flip()
            clock.tick(30)

        pygame.quit()

if __name__ == '__main__':
    try:
        validate_temp_zones()
        monitor = TempMonitor()

        # Set signal handler for graceful shutdown
        signal.signal(signal.SIGINT, lambda s, f: setattr(monitor, 'running', False))

        # Start background threads
        threads = [
            threading.Thread(target=monitor.read_serial, daemon=True),
            threading.Thread(target=monitor.process_temperature_data, daemon=True)
        ]

        for thread in threads:
            thread.start()

        # Run UI in the main thread
        monitor.ui_thread()

        # Stop other threads gracefully after UI exits
        monitor.running = False
        for thread in threads:
            thread.join(timeout=1.0)

    except KeyboardInterrupt:
        monitor.running = False
    finally:
        pygame.quit()
        sys.exit(0)
