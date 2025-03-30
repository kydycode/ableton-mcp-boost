# ableton_mcp_server.py
from mcp.server.fastmcp import FastMCP, Context
import socket
import json
import logging
from dataclasses import dataclass
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict, Any, List, Union

# Configure logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("AbletonMCPServer")

@dataclass
class AbletonConnection:
    host: str
    port: int
    sock: socket.socket = None
    
    def connect(self) -> bool:
        """Connect to the Ableton Remote Script socket server"""
        if self.sock:
            return True
            
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((self.host, self.port))
            logger.info(f"Connected to Ableton at {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Ableton: {str(e)}")
            self.sock = None
            return False
    
    def disconnect(self):
        """Disconnect from the Ableton Remote Script"""
        if self.sock:
            try:
                self.sock.close()
            except Exception as e:
                logger.error(f"Error disconnecting from Ableton: {str(e)}")
            finally:
                self.sock = None

    def receive_full_response(self, sock, buffer_size=8192):
        """Receive the complete response, potentially in multiple chunks"""
        chunks = []
        sock.settimeout(15.0)  # Increased timeout for operations that might take longer
        
        try:
            while True:
                try:
                    chunk = sock.recv(buffer_size)
                    if not chunk:
                        if not chunks:
                            raise Exception("Connection closed before receiving any data")
                        break
                    
                    chunks.append(chunk)
                    
                    # Check if we've received a complete JSON object
                    try:
                        data = b''.join(chunks)
                        json.loads(data.decode('utf-8'))
                        logger.info(f"Received complete response ({len(data)} bytes)")
                        return data
                    except json.JSONDecodeError:
                        # Incomplete JSON, continue receiving
                        continue
                except socket.timeout:
                    logger.warning("Socket timeout during chunked receive")
                    break
                except (ConnectionError, BrokenPipeError, ConnectionResetError) as e:
                    logger.error(f"Socket connection error during receive: {str(e)}")
                    raise
        except Exception as e:
            logger.error(f"Error during receive: {str(e)}")
            raise
            
        # If we get here, we either timed out or broke out of the loop
        if chunks:
            data = b''.join(chunks)
            logger.info(f"Returning data after receive completion ({len(data)} bytes)")
            try:
                json.loads(data.decode('utf-8'))
                return data
            except json.JSONDecodeError:
                raise Exception("Incomplete JSON response received")
        else:
            raise Exception("No data received")

    def send_command(self, command_type: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Send a command to Ableton and return the response"""
        if not self.sock and not self.connect():
            raise ConnectionError("Not connected to Ableton")
        
        command = {
            "type": command_type,
            "params": params or {}
        }
        
        # Check if this is a state-modifying command
        is_modifying_command = command_type in [
            "create_midi_track", "create_audio_track", "set_track_name",
            "create_clip", "add_notes_to_clip", "set_clip_name",
            "set_tempo", "fire_clip", "stop_clip", "set_device_parameter",
            "start_playback", "stop_playback", "load_instrument_or_effect"
        ]
        
        try:
            logger.info(f"Sending command: {command_type} with params: {params}")
            
            # Send the command
            self.sock.sendall(json.dumps(command).encode('utf-8'))
            logger.info(f"Command sent, waiting for response...")
            
            # For state-modifying commands, add a small delay to give Ableton time to process
            if is_modifying_command:
                import time
                time.sleep(0.1)  # 100ms delay
            
            # Set timeout based on command type
            timeout = 15.0 if is_modifying_command else 10.0
            self.sock.settimeout(timeout)
            
            # Receive the response
            response_data = self.receive_full_response(self.sock)
            logger.info(f"Received {len(response_data)} bytes of data")
            
            # Parse the response
            response = json.loads(response_data.decode('utf-8'))
            logger.info(f"Response parsed, status: {response.get('status', 'unknown')}")
            
            if response.get("status") == "error":
                logger.error(f"Ableton error: {response.get('message')}")
                raise Exception(response.get("message", "Unknown error from Ableton"))
            
            # For state-modifying commands, add another small delay after receiving response
            if is_modifying_command:
                import time
                time.sleep(0.1)  # 100ms delay
            
            return response.get("result", {})
        except socket.timeout:
            logger.error("Socket timeout while waiting for response from Ableton")
            self.sock = None
            raise Exception("Timeout waiting for Ableton response")
        except (ConnectionError, BrokenPipeError, ConnectionResetError) as e:
            logger.error(f"Socket connection error: {str(e)}")
            self.sock = None
            raise Exception(f"Connection to Ableton lost: {str(e)}")
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON response from Ableton: {str(e)}")
            if 'response_data' in locals() and response_data:
                logger.error(f"Raw response (first 200 bytes): {response_data[:200]}")
            self.sock = None
            raise Exception(f"Invalid response from Ableton: {str(e)}")
        except Exception as e:
            logger.error(f"Error communicating with Ableton: {str(e)}")
            self.sock = None
            raise Exception(f"Communication error with Ableton: {str(e)}")

@asynccontextmanager
async def server_lifespan(server: FastMCP) -> AsyncIterator[Dict[str, Any]]:
    """Manage server startup and shutdown lifecycle"""
    try:
        logger.info("AbletonMCP server starting up")
        
        try:
            ableton = get_ableton_connection()
            logger.info("Successfully connected to Ableton on startup")
        except Exception as e:
            logger.warning(f"Could not connect to Ableton on startup: {str(e)}")
            logger.warning("Make sure the Ableton Remote Script is running")
        
        yield {}
    finally:
        global _ableton_connection
        if _ableton_connection:
            logger.info("Disconnecting from Ableton on shutdown")
            _ableton_connection.disconnect()
            _ableton_connection = None
        logger.info("AbletonMCP server shut down")

# Create the MCP server with lifespan support
mcp = FastMCP(
    "AbletonMCP",
    description="Ableton Live integration through the Model Context Protocol",
    lifespan=server_lifespan
)

# Global connection for resources
_ableton_connection = None

def get_ableton_connection():
    """Get or create a persistent Ableton connection"""
    global _ableton_connection
    
    if _ableton_connection is not None:
        try:
            # Test the connection with a simple ping
            # We'll try to send an empty message, which should fail if the connection is dead
            # but won't affect Ableton if it's alive
            _ableton_connection.sock.settimeout(1.0)
            _ableton_connection.sock.sendall(b'')
            return _ableton_connection
        except Exception as e:
            logger.warning(f"Existing connection is no longer valid: {str(e)}")
            try:
                _ableton_connection.disconnect()
            except:
                pass
            _ableton_connection = None
    
    # Connection doesn't exist or is invalid, create a new one
    if _ableton_connection is None:
        # Try to connect up to 3 times with a short delay between attempts
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                logger.info(f"Connecting to Ableton (attempt {attempt}/{max_attempts})...")
                _ableton_connection = AbletonConnection(host="localhost", port=9877)
                if _ableton_connection.connect():
                    logger.info("Created new persistent connection to Ableton")
                    
                    # Validate connection with a simple command
                    try:
                        # Get session info as a test
                        _ableton_connection.send_command("get_session_info")
                        logger.info("Connection validated successfully")
                        return _ableton_connection
                    except Exception as e:
                        logger.error(f"Connection validation failed: {str(e)}")
                        _ableton_connection.disconnect()
                        _ableton_connection = None
                        # Continue to next attempt
                else:
                    _ableton_connection = None
            except Exception as e:
                logger.error(f"Connection attempt {attempt} failed: {str(e)}")
                if _ableton_connection:
                    _ableton_connection.disconnect()
                    _ableton_connection = None
            
            # Wait before trying again, but only if we have more attempts left
            if attempt < max_attempts:
                import time
                time.sleep(1.0)
        
        # If we get here, all connection attempts failed
        if _ableton_connection is None:
            logger.error("Failed to connect to Ableton after multiple attempts")
            raise Exception("Could not connect to Ableton. Make sure the Remote Script is running.")
    
    return _ableton_connection


# Core Tool endpoints

@mcp.tool()
def get_session_info(ctx: Context) -> str:
    """Get detailed information about the current Ableton session"""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_session_info")
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting session info from Ableton: {str(e)}")
        return f"Error getting session info: {str(e)}"

@mcp.tool()
def get_track_info(ctx: Context, track_index: int) -> str:
    """
    Get detailed information about a specific track in Ableton.
    
    Parameters:
    - track_index: The index of the track to get information about
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_track_info", {"track_index": track_index})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting track info from Ableton: {str(e)}")
        return f"Error getting track info: {str(e)}"

@mcp.tool()
def create_midi_track(ctx: Context, index: int = -1) -> str:
    """
    Create a new MIDI track in the Ableton session.
    
    Parameters:
    - index: The index to insert the track at (-1 = end of list)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("create_midi_track", {"index": index})
        return f"Created new MIDI track: {result.get('name', 'unknown')}"
    except Exception as e:
        logger.error(f"Error creating MIDI track: {str(e)}")
        return f"Error creating MIDI track: {str(e)}"


@mcp.tool()
def set_track_name(ctx: Context, track_index: int, name: str) -> str:
    """
    Set the name of a track.
    
    Parameters:
    - track_index: The index of the track to rename
    - name: The new name for the track
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_name", {"track_index": track_index, "name": name})
        return f"Renamed track to: {result.get('name', name)}"
    except Exception as e:
        logger.error(f"Error setting track name: {str(e)}")
        return f"Error setting track name: {str(e)}"

@mcp.tool()
def create_clip(ctx: Context, track_index: int, clip_index: int, length: float = 4.0) -> str:
    """
    Create a new MIDI clip in the specified track and clip slot.
    
    Parameters:
    - track_index: The index of the track to create the clip in
    - clip_index: The index of the clip slot to create the clip in
    - length: The length of the clip in beats (default: 4.0)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("create_clip", {
            "track_index": track_index, 
            "clip_index": clip_index, 
            "length": length
        })
        return f"Created new clip at track {track_index}, slot {clip_index} with length {length} beats"
    except Exception as e:
        logger.error(f"Error creating clip: {str(e)}")
        return f"Error creating clip: {str(e)}"

@mcp.tool()
def add_notes_to_clip(
    ctx: Context, 
    track_index: int, 
    clip_index: int, 
    notes: List[Dict[str, Union[int, float, bool]]]
) -> str:
    """
    Add MIDI notes to a clip.
    
    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - notes: List of note dictionaries, each with pitch, start_time, duration, velocity, and mute
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("add_notes_to_clip", {
            "track_index": track_index,
            "clip_index": clip_index,
            "notes": notes
        })
        return f"Added {len(notes)} notes to clip at track {track_index}, slot {clip_index}"
    except Exception as e:
        logger.error(f"Error adding notes to clip: {str(e)}")
        return f"Error adding notes to clip: {str(e)}"

@mcp.tool()
def set_clip_name(ctx: Context, track_index: int, clip_index: int, name: str) -> str:
    """
    Set the name of a clip.
    
    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - name: The new name for the clip
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_clip_name", {
            "track_index": track_index,
            "clip_index": clip_index,
            "name": name
        })
        return f"Renamed clip at track {track_index}, slot {clip_index} to '{name}'"
    except Exception as e:
        logger.error(f"Error setting clip name: {str(e)}")
        return f"Error setting clip name: {str(e)}"

@mcp.tool()
def set_tempo(ctx: Context, tempo: float) -> str:
    """
    Set the tempo of the Ableton session.
    
    Parameters:
    - tempo: The new tempo in BPM
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_tempo", {"tempo": tempo})
        return f"Set tempo to {tempo} BPM"
    except Exception as e:
        logger.error(f"Error setting tempo: {str(e)}")
        return f"Error setting tempo: {str(e)}"


@mcp.tool()
def load_instrument_or_effect(ctx: Context, track_index: int, uri: str) -> str:
    """
    Load an instrument or effect onto a track using its URI.
    
    Parameters:
    - track_index: The index of the track to load the instrument on
    - uri: The URI of the instrument or effect to load (e.g., 'query:Synths#Instrument%20Rack:Bass:FileId_5116')
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("load_browser_item", {
            "track_index": track_index,
            "item_uri": uri
        })
        
        # Check if the instrument was loaded successfully
        if result.get("loaded", False):
            new_devices = result.get("new_devices", [])
            if new_devices:
                return f"Loaded instrument with URI '{uri}' on track {track_index}. New devices: {', '.join(new_devices)}"
            else:
                devices = result.get("devices_after", [])
                return f"Loaded instrument with URI '{uri}' on track {track_index}. Devices on track: {', '.join(devices)}"
        else:
            return f"Failed to load instrument with URI '{uri}'"
    except Exception as e:
        logger.error(f"Error loading instrument by URI: {str(e)}")
        return f"Error loading instrument by URI: {str(e)}"

@mcp.tool()
def fire_clip(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Start playing a clip.
    
    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("fire_clip", {
            "track_index": track_index,
            "clip_index": clip_index
        })
        return f"Started playing clip at track {track_index}, slot {clip_index}"
    except Exception as e:
        logger.error(f"Error firing clip: {str(e)}")
        return f"Error firing clip: {str(e)}"

@mcp.tool()
def stop_clip(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Stop playing a clip.
    
    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("stop_clip", {
            "track_index": track_index,
            "clip_index": clip_index
        })
        return f"Stopped clip at track {track_index}, slot {clip_index}"
    except Exception as e:
        logger.error(f"Error stopping clip: {str(e)}")
        return f"Error stopping clip: {str(e)}"

@mcp.tool()
def start_playback(ctx: Context) -> str:
    """Start playing the Ableton session."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("start_playback")
        return "Started playback"
    except Exception as e:
        logger.error(f"Error starting playback: {str(e)}")
        return f"Error starting playback: {str(e)}"

@mcp.tool()
def stop_playback(ctx: Context) -> str:
    """Stop playing the Ableton session."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("stop_playback")
        return "Stopped playback"
    except Exception as e:
        logger.error(f"Error stopping playback: {str(e)}")
        return f"Error stopping playback: {str(e)}"

@mcp.tool()
def get_browser_tree(ctx: Context, category_type: str = "all") -> str:
    """
    Get a hierarchical tree of browser categories from Ableton.
    
    Parameters:
    - category_type: Type of categories to get ('all', 'instruments', 'sounds', 'drums', 'audio_effects', 'midi_effects')
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_browser_tree", {
            "category_type": category_type
        })
        
        # Check if we got any categories
        if "available_categories" in result and len(result.get("categories", [])) == 0:
            available_cats = result.get("available_categories", [])
            return (f"No categories found for '{category_type}'. "
                   f"Available browser categories: {', '.join(available_cats)}")
        
        # Format the tree in a more readable way
        total_folders = result.get("total_folders", 0)
        formatted_output = f"Browser tree for '{category_type}' (showing {total_folders} folders):\n\n"
        
        def format_tree(item, indent=0):
            output = ""
            if item:
                prefix = "  " * indent
                name = item.get("name", "Unknown")
                path = item.get("path", "")
                has_more = item.get("has_more", False)
                
                # Add this item
                output += f"{prefix}• {name}"
                if path:
                    output += f" (path: {path})"
                if has_more:
                    output += " [...]"
                output += "\n"
                
                # Add children
                for child in item.get("children", []):
                    output += format_tree(child, indent + 1)
            return output
        
        # Format each category
        for category in result.get("categories", []):
            formatted_output += format_tree(category)
            formatted_output += "\n"
        
        return formatted_output
    except Exception as e:
        error_msg = str(e)
        if "Browser is not available" in error_msg:
            logger.error(f"Browser is not available in Ableton: {error_msg}")
            return f"Error: The Ableton browser is not available. Make sure Ableton Live is fully loaded and try again."
        elif "Could not access Live application" in error_msg:
            logger.error(f"Could not access Live application: {error_msg}")
            return f"Error: Could not access the Ableton Live application. Make sure Ableton Live is running and the Remote Script is loaded."
        else:
            logger.error(f"Error getting browser tree: {error_msg}")
            return f"Error getting browser tree: {error_msg}"

@mcp.tool()
def get_browser_items_at_path(ctx: Context, path: str) -> str:
    """
    Get browser items at a specific path in Ableton's browser.
    
    Parameters:
    - path: Path in the format "category/folder/subfolder"
            where category is one of the available browser categories in Ableton
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_browser_items_at_path", {
            "path": path
        })
        
        # Check if there was an error with available categories
        if "error" in result and "available_categories" in result:
            error = result.get("error", "")
            available_cats = result.get("available_categories", [])
            return (f"Error: {error}\n"
                   f"Available browser categories: {', '.join(available_cats)}")
        
        return json.dumps(result, indent=2)
    except Exception as e:
        error_msg = str(e)
        if "Browser is not available" in error_msg:
            logger.error(f"Browser is not available in Ableton: {error_msg}")
            return f"Error: The Ableton browser is not available. Make sure Ableton Live is fully loaded and try again."
        elif "Could not access Live application" in error_msg:
            logger.error(f"Could not access Live application: {error_msg}")
            return f"Error: Could not access the Ableton Live application. Make sure Ableton Live is running and the Remote Script is loaded."
        elif "Unknown or unavailable category" in error_msg:
            logger.error(f"Invalid browser category: {error_msg}")
            return f"Error: {error_msg}. Please check the available categories using get_browser_tree."
        elif "Path part" in error_msg and "not found" in error_msg:
            logger.error(f"Path not found: {error_msg}")
            return f"Error: {error_msg}. Please check the path and try again."
        else:
            logger.error(f"Error getting browser items at path: {error_msg}")
            return f"Error getting browser items at path: {error_msg}"

@mcp.tool()
def load_drum_kit(ctx: Context, track_index: int, rack_uri: str, kit_path: str) -> str:
    """
    Load a drum rack and then load a specific drum kit into it.
    
    Parameters:
    - track_index: The index of the track to load on
    - rack_uri: The URI of the drum rack to load (e.g., 'Drums/Drum Rack')
    - kit_path: Path to the drum kit inside the browser (e.g., 'drums/acoustic/kit1')
    """
    try:
        ableton = get_ableton_connection()
        
        # Step 1: Load the drum rack
        result = ableton.send_command("load_browser_item", {
            "track_index": track_index,
            "item_uri": rack_uri
        })
        
        if not result.get("loaded", False):
            return f"Failed to load drum rack with URI '{rack_uri}'"
        
        # Step 2: Get the drum kit items at the specified path
        kit_result = ableton.send_command("get_browser_items_at_path", {
            "path": kit_path
        })
        
        if "error" in kit_result:
            return f"Loaded drum rack but failed to find drum kit: {kit_result.get('error')}"
        
        # Step 3: Find a loadable drum kit
        kit_items = kit_result.get("items", [])
        loadable_kits = [item for item in kit_items if item.get("is_loadable", False)]
        
        if not loadable_kits:
            return f"Loaded drum rack but no loadable drum kits found at '{kit_path}'"
        
        # Step 4: Load the first loadable kit
        kit_uri = loadable_kits[0].get("uri")
        load_result = ableton.send_command("load_browser_item", {
            "track_index": track_index,
            "item_uri": kit_uri
        })
        
        return f"Loaded drum rack and kit '{loadable_kits[0].get('name')}' on track {track_index}"
    except Exception as e:
        logger.error(f"Error loading drum kit: {str(e)}")
        return f"Error loading drum kit: {str(e)}"

# Arrangement Tools

@mcp.tool()
def create_arrangement_section(ctx: Context, section_type: str, length_bars: int, start_bar: int = -1) -> str:
    """
    Create a section in the arrangement (intro, verse, chorus, etc.) by duplicating clips into the arrangement view.
    
    Parameters:
    - section_type: Type of section to create (e.g. 'intro', 'verse', 'chorus', 'bridge', 'outro')
    - length_bars: Length of the section in bars
    - start_bar: Bar position to start the section (default: end of arrangement)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("create_arrangement_section", {
            "section_type": section_type,
            "length_bars": length_bars,
            "start_bar": start_bar
        })
        return f"Created {section_type} section with length {length_bars} bars at position {result.get('start_position', 'unknown')}"
    except Exception as e:
        logger.error(f"Error creating arrangement section: {str(e)}")
        return f"Error creating arrangement section: {str(e)}"

@mcp.tool()
def duplicate_section(ctx: Context, source_start_bar: int, source_end_bar: int, destination_bar: int, variation_level: float = 0.0) -> str:
    """
    Duplicate a section of the arrangement with optional variations.
    
    Parameters:
    - source_start_bar: Start bar of the section to duplicate
    - source_end_bar: End bar of the section to duplicate
    - destination_bar: Bar position to paste the duplicated section
    - variation_level: Amount of variation to apply (0.0 = exact copy, 1.0 = maximum variation)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("duplicate_section", {
            "source_start_bar": source_start_bar,
            "source_end_bar": source_end_bar,
            "destination_bar": destination_bar,
            "variation_level": variation_level
        })
        return f"Duplicated section from bar {source_start_bar} to {source_end_bar}, inserted at bar {destination_bar}"
    except Exception as e:
        logger.error(f"Error duplicating section: {str(e)}")
        return f"Error duplicating section: {str(e)}"

@mcp.tool()
def create_transition(ctx: Context, from_bar: int, to_bar: int, transition_type: str, length_beats: int = 4) -> str:
    """
    Create a transition between two sections in the arrangement.
    
    Parameters:
    - from_bar: Bar position where the transition starts
    - to_bar: Bar position where the transition ends
    - transition_type: Type of transition to create ('fill', 'riser', 'impact', 'downlifter', 'uplifter', 'cut')
    - length_beats: Length of the transition in beats
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("create_transition", {
            "from_bar": from_bar,
            "to_bar": to_bar,
            "transition_type": transition_type,
            "length_beats": length_beats
        })
        return f"Created {transition_type} transition from bar {from_bar} to {to_bar}"
    except Exception as e:
        logger.error(f"Error creating transition: {str(e)}")
        return f"Error creating transition: {str(e)}"

@mcp.tool()
def convert_session_to_arrangement(ctx: Context, structure: List[Dict[str, Union[str, int]]]) -> str:
    """
    Convert session clips to arrangement based on specified structure.
    
    Parameters:
    - structure: List of sections to create, each with a type, length and optional track selection
                 Example: [{"type": "intro", "length_bars": 8}, {"type": "verse", "length_bars": 16}]
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("convert_session_to_arrangement", {
            "structure": structure
        })
        return f"Created arrangement with {len(structure)} sections. Total length: {result.get('total_length_bars', 0)} bars"
    except Exception as e:
        logger.error(f"Error converting session to arrangement: {str(e)}")
        return f"Error converting session to arrangement: {str(e)}"

# Follow Actions Tools

@mcp.tool()
def set_clip_follow_action_time(ctx: Context, track_index: int, clip_index: int, time_beats: float) -> str:
    """
    Set the follow action time for a clip in beats.
    
    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - time_beats: The time in beats after which the follow action will be triggered
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_clip_follow_action_time", {
            "track_index": track_index,
            "clip_index": clip_index,
            "time_beats": time_beats
        })
        return f"Set follow action time to {time_beats} beats for clip at track {track_index}, slot {clip_index}"
    except Exception as e:
        logger.error(f"Error setting clip follow action time: {str(e)}")
        return f"Error setting clip follow action time: {str(e)}"

@mcp.tool()
def set_clip_follow_action(ctx: Context, track_index: int, clip_index: int, action_type: str, probability: float = 1.0) -> str:
    """
    Set the follow action for a clip.
    
    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - action_type: The type of follow action to set ('none', 'next', 'prev', 'first', 'last', 'any', 'other')
    - probability: The probability of this action being triggered (0.0 to 1.0, default: 1.0)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_clip_follow_action", {
            "track_index": track_index,
            "clip_index": clip_index,
            "action_type": action_type,
            "probability": probability
        })
        return f"Set follow action to '{action_type}' with probability {probability} for clip at track {track_index}, slot {clip_index}"
    except Exception as e:
        logger.error(f"Error setting clip follow action: {str(e)}")
        return f"Error setting clip follow action: {str(e)}"

@mcp.tool()
def set_clip_follow_action_linked(ctx: Context, track_index: int, clip_index: int, linked: bool = True) -> str:
    """
    Set whether the follow action timing is linked to the clip length.
    
    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - linked: Whether the follow action time should be linked to the clip length (default: True)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_clip_follow_action_linked", {
            "track_index": track_index,
            "clip_index": clip_index,
            "linked": linked
        })
        linked_status = "linked to clip length" if linked else "using custom time"
        return f"Set follow action timing to be {linked_status} for clip at track {track_index}, slot {clip_index}"
    except Exception as e:
        logger.error(f"Error setting clip follow action linked status: {str(e)}")
        return f"Error setting clip follow action linked status: {str(e)}"

@mcp.tool()
def setup_clip_sequence(ctx: Context, track_index: int, start_clip_index: int, end_clip_index: int) -> str:
    """
    Setup a sequence of clips with follow actions to play in order.
    
    Parameters:
    - track_index: The index of the track containing the clips
    - start_clip_index: The index of the first clip in the sequence
    - end_clip_index: The index of the last clip in the sequence
    """
    try:
        ableton = get_ableton_connection()
        
        # Validate the track exists
        try:
            track_info = ableton.send_command("get_track_info", {"track_index": track_index})
        except Exception as e:
            return f"Error accessing track {track_index}: {str(e)}"
        
        # Process each clip in the sequence
        clips_processed = 0
        for clip_index in range(start_clip_index, end_clip_index + 1):
            try:
                # Check if the clip slot has a clip
                result = ableton.send_command("get_track_info", {"track_index": track_index})
                clip_slots = result.get("clip_slots", [])
                
                if clip_index >= len(clip_slots) or not clip_slots[clip_index].get("has_clip", False):
                    logger.warning(f"No clip at track {track_index}, slot {clip_index}, skipping")
                    continue
                
                # Get clip info
                clip_info = clip_slots[clip_index].get("clip", {})
                
                # Set follow action to "next" with 100% probability
                ableton.send_command("set_clip_follow_action", {
                    "track_index": track_index,
                    "clip_index": clip_index,
                    "action_type": "next",
                    "probability": 1.0
                })
                
                # Set follow action time to match clip length
                ableton.send_command("set_clip_follow_action_time", {
                    "track_index": track_index,
                    "clip_index": clip_index,
                    "time_beats": clip_info.get("length", 4.0) * 4.0  # Convert to beats assuming 4/4 time
                })
                
                # Set follow action to be linked to clip length
                ableton.send_command("set_clip_follow_action_linked", {
                    "track_index": track_index,
                    "clip_index": clip_index,
                    "linked": True
                })
                
                clips_processed += 1
                
            except Exception as e:
                logger.error(f"Error setting up follow action for clip {clip_index}: {str(e)}")
                # Continue with next clip even if this one fails
        
        # Handle special case for last clip to loop back to the first
        if clips_processed > 0 and end_clip_index < len(clip_slots) and clip_slots[end_clip_index].get("has_clip", False):
            try:
                # Set the last clip to go back to the first one
                ableton.send_command("set_clip_follow_action", {
                    "track_index": track_index,
                    "clip_index": end_clip_index,
                    "action_type": "first" if start_clip_index == 0 else "other",  # Use "first" if starting at 0, otherwise use specific clip
                    "probability": 1.0
                })
            except Exception as e:
                logger.error(f"Error setting loop back action for last clip: {str(e)}")
        
        return f"Set up follow actions for {clips_processed} clips in track {track_index} from clip {start_clip_index} to {end_clip_index}"
    except Exception as e:
        logger.error(f"Error setting up clip sequence: {str(e)}")
        return f"Error setting up clip sequence: {str(e)}"

@mcp.tool()
def setup_project_follow_actions(ctx: Context, loop_back: bool = True) -> str:
    """
    Setup follow actions for all tracks in the project.
    This sets all clips to play in sequence (top to bottom) on each track.
    
    Parameters:
    - loop_back: Whether the last clip should loop back to the first clip in each track (default: True)
    """
    try:
        ableton = get_ableton_connection()
        
        # Get session info to determine number of tracks
        session_info = ableton.send_command("get_session_info")
        track_count = session_info.get("track_count", 0)
        
        if track_count == 0:
            return "No tracks found in the project"
        
        total_clips_processed = 0
        tracks_processed = 0
        
        # Process each track
        for track_index in range(track_count):
            try:
                track_info = ableton.send_command("get_track_info", {"track_index": track_index})
                clip_slots = track_info.get("clip_slots", [])
                
                # Find clips in this track
                clips_with_content = []
                for i, slot in enumerate(clip_slots):
                    if slot.get("has_clip", False):
                        clips_with_content.append(i)
                
                if not clips_with_content:
                    logger.info(f"No clips found in track {track_index}, skipping")
                    continue
                
                # Process clips in sequence
                clips_processed = 0
                for i, clip_index in enumerate(clips_with_content):
                    try:
                        # Get clip info
                        clip_info = clip_slots[clip_index].get("clip", {})
                        
                        # Set follow action to "next" with 100% probability
                        action_type = "next"
                        
                        # If this is the last clip and loop_back is True, set action to go back to first clip
                        if i == len(clips_with_content) - 1 and loop_back:
                            if clips_with_content[0] == 0:
                                action_type = "first"
                            else:
                                action_type = "other"  # Would need to set specific clip index for "other"
                        
                        ableton.send_command("set_clip_follow_action", {
                            "track_index": track_index,
                            "clip_index": clip_index,
                            "action_type": action_type,
                            "probability": 1.0
                        })
                        
                        # Set follow action time to match clip length and link it
                        ableton.send_command("set_clip_follow_action_time", {
                            "track_index": track_index,
                            "clip_index": clip_index,
                            "time_beats": clip_info.get("length", 4.0)
                        })
                        
                        ableton.send_command("set_clip_follow_action_linked", {
                            "track_index": track_index,
                            "clip_index": clip_index,
                            "linked": True
                        })
                        
                        clips_processed += 1
                        
                    except Exception as e:
                        logger.error(f"Error setting up follow action for track {track_index}, clip {clip_index}: {str(e)}")
                        # Continue with next clip
                
                if clips_processed > 0:
                    tracks_processed += 1
                    total_clips_processed += clips_processed
                    logger.info(f"Processed {clips_processed} clips in track {track_index}")
                
            except Exception as e:
                logger.error(f"Error processing track {track_index}: {str(e)}")
                # Continue with next track
        
        return f"Set up follow actions for {total_clips_processed} clips across {tracks_processed} tracks"
    except Exception as e:
        logger.error(f"Error setting up project follow actions: {str(e)}")
        return f"Error setting up project follow actions: {str(e)}"

# Main execution
def main():
    """Run the MCP server"""
    mcp.run()

if __name__ == "__main__":
    main()