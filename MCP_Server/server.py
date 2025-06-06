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
            "start_playback", "stop_playback", "load_instrument_or_effect",
            # Added arrangement-related commands
            "create_arrangement_section", "duplicate_section", 
            "create_transition", "convert_session_to_arrangement",
            "add_automation_to_clip", "create_audio_track", 
            "insert_arrangement_clip", "duplicate_clip_to_arrangement",
            "set_locators", "set_arrangement_loop"
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
        logger.info("AbletonMCPboost server starting up")
        
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
        logger.info("AbletonMCPboost server shut down")

# Create the MCP server with lifespan support
mcp = FastMCP(
    "AbletonMCPboost",
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
        error_msg = str(e)
        logger.error(f"Error converting session to arrangement: {error_msg}")
        
        # Handle specific API compatibility errors
        if "clear_arrangement" in error_msg:
            return ("Error: The 'clear_arrangement' method is not available in your version of Ableton Live. "
                   "Try using create_complex_arrangement instead, which can work without clearing the arrangement.")
        else:
            return f"Error converting session to arrangement: {error_msg}"

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
def add_automation_to_clip(
    ctx: Context, 
    track_index: int, 
    clip_index: int, 
    parameter_name: str,
    points: List[Dict[str, float]]
) -> str:
    """
    Add automation for a parameter to a clip
    
    Args:
        track_index: Index of the track containing the clip
        clip_index: Index of the clip to add automation to
        parameter_name: Name of the parameter to automate (e.g. "volume", "panning", "device1_param1")
        points: List of automation points [{"time": time_in_beats, "value": parameter_value}, ...]
        
    Returns:
        Information about the added automation
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "add_automation_to_clip", 
            {
                "track_index": track_index,
                "clip_index": clip_index,
                "parameter_name": parameter_name,
                "points": points
            }
        )
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"Error adding automation to clip: {str(e)}"

@mcp.tool()
def create_audio_track(ctx: Context, index: int = -1) -> str:
    """
    Create a new audio track
    
    Args:
        index: Index where the track should be created (-1 for end of track list)
        
    Returns:
        Information about the created track
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("create_audio_track", {"index": index})
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"Error creating audio track: {str(e)}"

@mcp.tool()
def insert_arrangement_clip(
    ctx: Context,
    track_index: int,
    start_time: float,
    length: float,
    is_audio: bool = False
) -> str:
    """
    Insert a clip directly in the arrangement view
    
    Args:
        track_index: Index of the track
        start_time: Start time in beats
        length: Length in beats
        is_audio: Whether this is an audio clip (default: false for MIDI)
        
    Returns:
        Information about the inserted clip
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "insert_arrangement_clip", 
            {
                "track_index": track_index,
                "start_time": start_time,
                "length": length,
                "is_audio": is_audio
            }
        )
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"Error inserting arrangement clip: {str(e)}"

@mcp.tool()
def duplicate_clip_to_arrangement(
    ctx: Context,
    track_index: int,
    clip_index: int,
    arrangement_time: float
) -> str:
    """
    Duplicate a session view clip to the arrangement view
    
    Args:
        track_index: Index of the track containing the clip
        clip_index: Index of the clip in session view
        arrangement_time: Time position in the arrangement view (in beats)
        
    Returns:
        Information about the duplicated clip
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "duplicate_clip_to_arrangement", 
            {
                "track_index": track_index,
                "clip_index": clip_index,
                "arrangement_time": arrangement_time
            }
        )
        return json.dumps(result, indent=2)
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error duplicating clip to arrangement: {error_msg}")
        
        # Handle specific API compatibility errors
        if "duplicate_clip_to" in error_msg:
            return ("Error: The 'duplicate_clip_to' method is not available in your version of Ableton Live. "
                   "The script will try to create a new clip and copy the content instead.")
        else:
            return f"Error duplicating clip to arrangement: {error_msg}"

@mcp.tool()
def set_locators(
    ctx: Context,
    start_time: float,
    end_time: float,
    name: str = ""
) -> str:
    """
    Set arrangement locators (start/end markers)
    
    Args:
        start_time: Start time in beats
        end_time: End time in beats
        name: Name for the locator region
        
    Returns:
        Information about the set locators
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "set_locators", 
            {
                "start_time": start_time,
                "end_time": end_time,
                "name": name
            }
        )
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"Error setting locators: {str(e)}"

@mcp.tool()
def set_arrangement_loop(
    ctx: Context,
    start_time: float,
    end_time: float,
    enabled: bool = True
) -> str:
    """
    Set the arrangement loop region
    
    Args:
        start_time: Loop start time in beats
        end_time: Loop end time in beats
        enabled: Whether loop is enabled
        
    Returns:
        Information about the loop settings
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "set_arrangement_loop", 
            {
                "start_time": start_time,
                "end_time": end_time,
                "enabled": enabled
            }
        )
        return json.dumps(result, indent=2)
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error setting arrangement loop: {error_msg}")
        
        # Handle specific API compatibility errors
        if "loop_end" in error_msg:
            return ("Error: The 'loop_end' property is not available in your version of Ableton Live. "
                   "The script will try to use 'loop_length' instead.")
        else:
            return f"Error setting arrangement loop: {error_msg}"

@mcp.tool()
def get_arrangement_info(ctx: Context) -> str:
    """
    Get information about the current arrangement
    
    Returns:
        Information about the arrangement tracks, clips, and structure
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_arrangement_info", {})
        return json.dumps(result, indent=2)
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error getting arrangement info: {error_msg}")
        
        # Handle specific API compatibility errors
        if "loop_end" in error_msg:
            return ("Error: Some arrangement properties are not available in your version of Ableton Live. "
                   "Try using more specific tools like get_time_signatures or get_arrangement_markers instead.")
        else:
            return f"Error getting arrangement info: {error_msg}"

@mcp.tool()
def get_track_arrangement_clips(ctx: Context, track_index: int) -> str:
    """
    Get all clips in the arrangement view for a specific track
    
    Args:
        track_index: Index of the track
        
    Returns:
        Information about all arrangement clips on the track
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "get_track_arrangement_clips", 
            {
                "track_index": track_index
            }
        )
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"Error getting track arrangement clips: {str(e)}"

@mcp.tool()
def set_time_signature(ctx: Context, numerator: int, denominator: int, bar_position: int = 1) -> str:
    """
    Set the time signature at a specific bar in the arrangement
    
    Args:
        numerator: Time signature numerator (e.g., 4 for 4/4)
        denominator: Time signature denominator (e.g., 4 for 4/4)
        bar_position: Bar where the time signature should be set (default: 1, the beginning)
        
    Returns:
        Information about the set time signature
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "set_time_signature", 
            {
                "numerator": numerator,
                "denominator": denominator,
                "bar_position": bar_position
            }
        )
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"Error setting time signature: {str(e)}"

@mcp.tool()
def get_time_signatures(ctx: Context) -> str:
    """
    Get all time signatures in the arrangement
    
    Returns:
        List of time signatures in the arrangement
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_time_signatures", {})
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"Error getting time signatures: {str(e)}"

@mcp.tool()
def set_playhead_position(ctx: Context, time: float) -> str:
    """
    Set the playhead position in the arrangement
    
    Args:
        time: Time position in beats
        
    Returns:
        Information about the new playhead position
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_playhead_position", {"time": time})
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"Error setting playhead position: {str(e)}"

@mcp.tool()
def create_arrangement_marker(ctx: Context, name: str, time: float) -> str:
    """
    Create a marker in the arrangement at the specified position
    
    Args:
        name: Name of the marker
        time: Time position in beats
        
    Returns:
        Information about the created marker
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "create_arrangement_marker", 
            {
                "name": name,
                "time": time
            }
        )
        return json.dumps(result, indent=2)
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error creating arrangement marker: {error_msg}")
        
        if "set_or_delete_cue" in error_msg:
            return ("Error: The 'set_or_delete_cue' method signature has changed in your version of Ableton Live. "
                   "Try using locator points from Ableton's UI directly.")
        else:
            return f"Error creating arrangement marker: {error_msg}"

@mcp.tool()
def get_arrangement_markers(ctx: Context) -> str:
    """
    Get all markers in the arrangement
    
    Returns:
        List of all markers in the arrangement
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_arrangement_markers", {})
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"Error getting arrangement markers: {str(e)}"

@mcp.tool()
def create_complex_arrangement(
    ctx: Context, 
    structure: List[Dict[str, Any]],
    transitions: bool = True,
    arrange_automation: bool = True
) -> str:
    """
    Create a complete arrangement with complex structure
    
    Args:
        structure: List of sections [{
            "name": "Intro", 
            "type": "intro", 
            "length_bars": 8, 
            "energy_level": 0.3,
            "tracks": [{"index": 0, "clips": [0]}]
        }, ...]
        transitions: Whether to create transitions between sections
        arrange_automation: Whether to add automation for energy levels
        
    Returns:
        Information about the created arrangement
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "create_complex_arrangement", 
            {
                "structure": structure,
                "transitions": transitions,
                "arrange_automation": arrange_automation
            }
        )
        return json.dumps(result, indent=2)
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error creating complex arrangement: {error_msg}")
        
        # Handle specific API compatibility errors
        if "clear_arrangement" in error_msg:
            return ("Error: The 'clear_arrangement' method is not available in your version of Ableton Live. "
                   "The script will try to create clips without clearing the arrangement.")
        elif "duplicate_clip_to" in error_msg:
            return ("Error: The 'duplicate_clip_to' method is not available in your version of Ableton Live. "
                   "The script will try to create clips and copy content manually.")
        else:
            return f"Error creating complex arrangement: {error_msg}"

@mcp.tool()
def quantize_arrangement_clips(ctx: Context, track_index: int = -1, quantize_amount: float = 1.0) -> str:
    """
    Quantize all clips in the arrangement
    
    Args:
        track_index: Track index to quantize (-1 for all tracks)
        quantize_amount: Quantization amount (0.0 to 1.0)
        
    Returns:
        Information about the quantized clips
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "quantize_arrangement_clips", 
            {
                "track_index": track_index,
                "quantize_amount": quantize_amount
            }
        )
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"Error quantizing arrangement clips: {str(e)}"

@mcp.tool()
def consolidate_arrangement_selection(ctx: Context, start_time: float, end_time: float, track_index: int) -> str:
    """
    Consolidate a selection in the arrangement to a new clip
    
    Args:
        start_time: Start time in beats
        end_time: End time in beats
        track_index: Track index to consolidate
        
    Returns:
        Information about the consolidated clip
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "consolidate_arrangement_selection", 
            {
                "start_time": start_time,
                "end_time": end_time,
                "track_index": track_index
            }
        )
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"Error consolidating arrangement selection: {str(e)}"

@mcp.tool()
def arrangement_record_helper(
    ctx: Context, 
    track_indices: List[int], 
    clip_indices: List[int], 
    start_time: float, 
    duration: float = 4.0
) -> str:
    """
    Helper tool to record session clips to arrangement view when create_clip isn't available.
    This positions the playhead, starts arrangement recording, fires the clips, and stops recording.
    
    Args:
        track_indices: List of track indices containing clips to fire
        clip_indices: List of clip indices to fire (must match track_indices length)
        start_time: Starting position in arrangement (beats)
        duration: How long to record for (beats)
        
    Returns:
        Information about the recording operation
    """
    try:
        if len(track_indices) != len(clip_indices):
            return "Error: track_indices and clip_indices must have the same length"
            
        ableton = get_ableton_connection()
        
        # Get current transport state
        session_info = ableton.send_command("get_session_info")
        was_playing = session_info.get("is_playing", False)
        tempo = session_info.get("tempo", 120.0)
        
        # Calculate how long we need to record in seconds
        duration_seconds = (duration / (tempo / 60.0))
        
        # Position playhead
        ableton.send_command("set_playhead_position", {"time": start_time})
        
        # Enable arrangement recording
        result = ableton.send_command("start_arrangement_recording", {})
        
        # Loop through and launch clips
        for i in range(len(track_indices)):
            track_index = track_indices[i]
            clip_index = clip_indices[i]
            
            # Fire clip
            ableton.send_command("fire_clip", {
                "track_index": track_index,
                "clip_index": clip_index
            })
        
        # Let the user know what's happening
        result_str = (f"Recording {len(track_indices)} clips to arrangement at position {start_time}. "
                     f"Recording will continue for approximately {duration_seconds:.1f} seconds.")
        
        # In a real implementation, we'd use a timer or other mechanism to stop recording 
        # after the duration. For now, we'll just let the user know they need to stop manually.
        result_str += "\nPlease stop recording manually when the clip(s) have played."
        
        return result_str
    except Exception as e:
        logger.error(f"Error with arrangement recording helper: {str(e)}")
        return f"Error setting up arrangement recording: {str(e)}"

@mcp.tool()
def start_arrangement_recording(ctx: Context) -> str:
    """
    Start recording in arrangement view
    
    Returns:
        Information about the recording state
    """
    try:
        ableton = get_ableton_connection()
        
        # Ensure we're in arrangement view
        ableton.send_command("show_arrangement_view", {})
        
        # Turn on arrangement record
        result = ableton.send_command("set_arrangement_record", {"enabled": True})
        
        # Start playback if not already playing
        play_result = ableton.send_command("start_playback", {})
        
        return "Arrangement recording started. Press Stop when finished."
    except Exception as e:
        logger.error(f"Error starting arrangement recording: {str(e)}")
        return f"Error starting arrangement recording: {str(e)}"

@mcp.tool()
def show_arrangement_view(ctx: Context) -> str:
    """
    Switch to arrangement view
    
    Returns:
        Information about the view change
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("show_arrangement_view", {})
        return "Switched to arrangement view"
    except Exception as e:
        logger.error(f"Error switching to arrangement view: {str(e)}")
        return f"Error switching to arrangement view: {str(e)}"

@mcp.tool()
def show_session_view(ctx: Context) -> str:
    """
    Switch to session view
    
    Returns:
        Information about the view change
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("show_session_view", {})
        return "Switched to session view"
    except Exception as e:
        logger.error(f"Error switching to session view: {str(e)}")
        return f"Error switching to session view: {str(e)}"

@mcp.tool()
def set_arrangement_record(ctx: Context, enabled: bool = True) -> str:
    """
    Enable or disable arrangement record mode
    
    Args:
        enabled: Whether to enable record mode
        
    Returns:
        Information about the record state
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_arrangement_record", {"enabled": enabled})
        state = "enabled" if enabled else "disabled"
        return f"Arrangement record mode {state}"
    except Exception as e:
        logger.error(f"Error setting arrangement record mode: {str(e)}")
        return f"Error setting arrangement record mode: {str(e)}"

@mcp.tool()
def arrangement_to_session(ctx: Context, track_index: int, start_time: float, end_time: float, target_clip_slot: int) -> str:
    """
    Copy a section of the arrangement to a session clip slot
    
    Args:
        track_index: Track to copy from and to
        start_time: Start time in the arrangement (beats)
        end_time: End time in the arrangement (beats)
        target_clip_slot: Target clip slot index in session view
        
    Returns:
        Information about the created session clip
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "arrangement_to_session", 
            {
                "track_index": track_index,
                "start_time": start_time,
                "end_time": end_time,
                "target_clip_slot": target_clip_slot
            }
        )
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error copying arrangement to session: {str(e)}")
        return f"Error copying arrangement to session: {str(e)}"

@mcp.tool()
def add_notes_to_arrangement_clip(
    ctx: Context, 
    track_index: int, 
    start_time: float, 
    notes: List[Dict[str, Union[int, float, bool]]],
    ensure_length: bool = True
) -> str:
    """
    Add MIDI notes to a clip in the arrangement view
    
    Args:
        track_index: Index of the track containing the clip
        start_time: Start time of the clip in beats
        notes: List of note objects with pitch, start_time, duration, velocity, and mute properties
        ensure_length: Whether to ensure the clip is resized to accommodate all notes (default: true)
        
    Returns:
        Information about the added notes
    """
    try:
        # Calculate required length if ensure_length is true
        max_note_end = 0
        if ensure_length:
            for note in notes:
                note_end = note.get("start_time", 0) + note.get("duration", 0.25)
                max_note_end = max(max_note_end, note_end)
            logger.info(f"Notes require length of at least: {max_note_end} beats")
        
        ableton = get_ableton_connection()
        
        # First, if ensure_length is true, check the current clip length
        if ensure_length:
            track_clips = ableton.send_command(
                "get_track_arrangement_clips",
                {"track_index": track_index}
            )
            
            # Find the clip at or near the start_time
            found_clip = False
            clip_length = 0
            if "clips" in track_clips:
                for clip in track_clips.get("clips", []):
                    clip_start = clip.get("start_time", 0)
                    if abs(clip_start - start_time) < 0.1:  # Within 0.1 beats
                        found_clip = True
                        clip_length = clip.get("length", 0)
                        logger.info(f"Found clip at {clip_start} with length {clip_length}")
                        break
            
            # If clip was found but is too short, try to resize it
            if found_clip and clip_length < max_note_end:
                logger.info(f"Clip length {clip_length} is less than required {max_note_end}, attempting resize")
                
                # Try to resize using set_clip_loop_end
                try:
                    ableton.send_command(
                        "set_clip_loop_end",
                        {
                            "track_index": track_index,
                            "clip_start_time": start_time,
                            "loop_end": max_note_end
                        }
                    )
                    logger.info(f"Resized clip to {max_note_end} beats")
                except Exception as e:
                    logger.warning(f"Could not resize clip: {str(e)}")
        
        # Now add the notes
        result = ableton.send_command(
            "add_notes_to_clip", 
            {
                "track_index": track_index,
                "clip_index": f"arrangement:{start_time}",
                "notes": notes
            }
        )
        
        # Include the max_note_end in the response
        if ensure_length and max_note_end > 0:
            result_dict = json.loads(result) if isinstance(result, str) else result
            if isinstance(result_dict, dict):
                result_dict["required_length"] = max_note_end
                result = json.dumps(result_dict, indent=2)
        
        return result
    except Exception as e:
        logger.error(f"Error adding notes to arrangement clip: {str(e)}")
        return f"Error adding notes to arrangement clip: {str(e)}"

@mcp.tool()
def create_arrangement_track(
    ctx: Context,
    track_name: str,
    clips: List[Dict[str, Any]],
    is_audio: bool = False,
    track_index: int = -1
) -> str:
    """
    Create a track and multiple clips in arrangement view in a single operation
    
    Args:
        track_name: Name for the new track
        clips: List of clip specifications with start_time, length, and optionally notes array
        is_audio: Whether to create an audio track (default: false for MIDI)
        track_index: Index to insert the new track at (-1 for end)
        
    Returns:
        Information about the created track and clips
    """
    try:
        ableton = get_ableton_connection()
        
        # Make sure we're in arrangement view
        ableton.send_command("show_arrangement_view", {})
        
        # Create the track
        track_result = {}
        if is_audio:
            track_result = ableton.send_command("create_audio_track", {"index": track_index})
        else:
            track_result = ableton.send_command("create_midi_track", {"index": track_index})
        
        # Get the resulting track index
        new_track_index = track_result.get("index", 0)
        
        # Set the track name
        ableton.send_command("set_track_name", {"track_index": new_track_index, "name": track_name})
        
        # Create each clip
        clip_results = []
        for clip_spec in clips:
            start_time = clip_spec.get("start_time", 0.0)
            length = clip_spec.get("length", 4.0)
            name = clip_spec.get("name", "")
            notes = clip_spec.get("notes", [])
            
            # Create the clip
            clip_result = ableton.send_command(
                "insert_arrangement_clip", 
                {
                    "track_index": new_track_index,
                    "start_time": start_time,
                    "length": length,
                    "is_audio": is_audio
                }
            )
            
            # Add notes if this is a MIDI clip with notes specified
            if not is_audio and notes:
                note_result = ableton.send_command(
                    "add_notes_to_clip",
                    {
                        "track_index": new_track_index,
                        "clip_index": f"arrangement:{start_time}",
                        "notes": notes
                    }
                )
            
            # Set clip name if specified
            if name:
                # We can't directly name arrangement clips, so we'll include it in the result
                clip_result["name"] = name
            
            clip_results.append({
                "start_time": start_time,
                "length": length,
                "name": name,
                "note_count": len(notes) if not is_audio else 0
            })
        
        # Return the comprehensive result
        result = {
            "track_index": new_track_index,
            "track_name": track_name,
            "is_audio": is_audio,
            "clip_count": len(clip_results),
            "clips": clip_results
        }
        
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error creating arrangement track: {str(e)}")
        return f"Error creating arrangement track: {str(e)}"

@mcp.tool()
def get_current_view(ctx: Context) -> str:
    """
    Get the current view in Ableton (Session or Arrangement)
    
    Returns:
        Information about the current view
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_current_view", {})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting current view: {str(e)}")
        return f"Error getting current view: {str(e)}"

# Main execution
def main():
    """Run the MCP server"""
    mcp.run()

if __name__ == "__main__":
    main()