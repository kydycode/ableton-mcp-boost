# AbletonMCP/init.py
from __future__ import absolute_import, print_function, unicode_literals

from _Framework.ControlSurface import ControlSurface
import socket
import json
import threading
import time
import traceback
import random

# Change queue import for Python 2
try:
    import Queue as queue  # Python 2
except ImportError:
    import queue  # Python 3

# Constants for socket communication
DEFAULT_PORT = 9877
HOST = "localhost"

def create_instance(c_instance):
    """Create and return the AbletonMCP script instance"""
    return AbletonMCP(c_instance)

class AbletonMCP(ControlSurface):
    """AbletonMCP Remote Script for Ableton Live"""
    
    def __init__(self, c_instance):
        """Initialize the control surface"""
        ControlSurface.__init__(self, c_instance)
        self.log_message("AbletonMCP Remote Script initializing...")
        
        # Socket server for communication
        self.server = None
        self.client_threads = []
        self.server_thread = None
        self.running = False
        
        # Cache the song reference for easier access
        self._song = self.song()
        
        # Start the socket server
        self.start_server()
        
        self.log_message("AbletonMCP initialized")
        
        # Show a message in Ableton
        self.show_message("AbletonMCP: Listening for commands on port " + str(DEFAULT_PORT))
    
    def disconnect(self):
        """Called when Ableton closes or the control surface is removed"""
        self.log_message("AbletonMCP disconnecting...")
        self.running = False
        
        # Stop the server
        if self.server:
            try:
                self.server.close()
            except:
                pass
        
        # Wait for the server thread to exit
        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(1.0)
            
        # Clean up any client threads
        for client_thread in self.client_threads[:]:
            if client_thread.is_alive():
                # We don't join them as they might be stuck
                self.log_message("Client thread still alive during disconnect")
        
        ControlSurface.disconnect(self)
        self.log_message("AbletonMCP disconnected")
    
    def start_server(self):
        """Start the socket server in a separate thread"""
        try:
            self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server.bind((HOST, DEFAULT_PORT))
            self.server.listen(5)  # Allow up to 5 pending connections
            
            self.running = True
            self.server_thread = threading.Thread(target=self._server_thread)
            self.server_thread.daemon = True
            self.server_thread.start()
            
            self.log_message("Server started on port " + str(DEFAULT_PORT))
        except Exception as e:
            self.log_message("Error starting server: " + str(e))
            self.show_message("AbletonMCP: Error starting server - " + str(e))
    
    def _server_thread(self):
        """Server thread implementation - handles client connections"""
        try:
            self.log_message("Server thread started")
            # Set a timeout to allow regular checking of running flag
            self.server.settimeout(1.0)
            
            while self.running:
                try:
                    # Accept connections with timeout
                    client, address = self.server.accept()
                    self.log_message("Connection accepted from " + str(address))
                    self.show_message("AbletonMCP: Client connected")
                    
                    # Handle client in a separate thread
                    client_thread = threading.Thread(
                        target=self._handle_client,
                        args=(client,)
                    )
                    client_thread.daemon = True
                    client_thread.start()
                    
                    # Keep track of client threads
                    self.client_threads.append(client_thread)
                    
                    # Clean up finished client threads
                    self.client_threads = [t for t in self.client_threads if t.is_alive()]
                    
                except socket.timeout:
                    # No connection yet, just continue
                    continue
                except Exception as e:
                    if self.running:  # Only log if still running
                        self.log_message("Server accept error: " + str(e))
                    time.sleep(0.5)
            
            self.log_message("Server thread stopped")
        except Exception as e:
            self.log_message("Server thread error: " + str(e))
    
    def _handle_client(self, client):
        """Handle communication with a connected client"""
        self.log_message("Client handler started")
        client.settimeout(None)  # No timeout for client socket
        buffer = ''  # Changed from b'' to '' for Python 2
        
        try:
            while self.running:
                try:
                    # Receive data
                    data = client.recv(8192)
                    
                    if not data:
                        # Client disconnected
                        self.log_message("Client disconnected")
                        break
                    
                    # Accumulate data in buffer with explicit encoding/decoding
                    try:
                        # Python 3: data is bytes, decode to string
                        buffer += data.decode('utf-8')
                    except AttributeError:
                        # Python 2: data is already string
                        buffer += data
                    
                    try:
                        # Try to parse command from buffer
                        command = json.loads(buffer)  # Removed decode('utf-8')
                        buffer = ''  # Clear buffer after successful parse
                        
                        self.log_message("Received command: " + str(command.get("type", "unknown")))
                        
                        # Process the command and get response
                        response = self._process_command(command)
                        
                        # Send the response with explicit encoding
                        try:
                            # Python 3: encode string to bytes
                            client.sendall(json.dumps(response).encode('utf-8'))
                        except AttributeError:
                            # Python 2: string is already bytes
                            client.sendall(json.dumps(response))
                    except ValueError:
                        # Incomplete data, wait for more
                        continue
                        
                except Exception as e:
                    self.log_message("Error handling client data: " + str(e))
                    self.log_message(traceback.format_exc())
                    
                    # Send error response if possible
                    error_response = {
                        "status": "error",
                        "message": str(e)
                    }
                    try:
                        # Python 3: encode string to bytes
                        client.sendall(json.dumps(error_response).encode('utf-8'))
                    except AttributeError:
                        # Python 2: string is already bytes
                        client.sendall(json.dumps(error_response))
                    except:
                        # If we can't send the error, the connection is probably dead
                        break
                    
                    # For serious errors, break the loop
                    if not isinstance(e, ValueError):
                        break
        except Exception as e:
            self.log_message("Error in client handler: " + str(e))
        finally:
            try:
                client.close()
            except:
                pass
            self.log_message("Client handler stopped")
    
    def _process_command(self, command):
        """Process a command from the client and return a response"""
        command_type = command.get("type", "")
        params = command.get("params", {})
        
        # Initialize response
        response = {
            "status": "success",
            "result": {}
        }
        
        try:
            # Route the command to the appropriate handler
            if command_type == "get_session_info":
                response["result"] = self._get_session_info()
            elif command_type == "get_track_info":
                track_index = params.get("track_index", 0)
                response["result"] = self._get_track_info(track_index)
            # Commands that modify Live's state should be scheduled on the main thread
            elif command_type in ["create_midi_track", "set_track_name", 
                                 "create_clip", "add_notes_to_clip", "set_clip_name", 
                                 "set_tempo", "fire_clip", "stop_clip",
                                 "start_playback", "stop_playback", "load_browser_item",
                                 "create_arrangement_section", "duplicate_section", 
                                 "create_transition", "convert_session_to_arrangement",
                                 "set_clip_follow_action_time", "set_clip_follow_action",
                                 "set_clip_follow_action_linked"]:
                # Use a thread-safe approach with a response queue
                response_queue = queue.Queue()
                
                # Define a function to execute on the main thread
                def main_thread_task():
                    try:
                        result = None
                        if command_type == "create_midi_track":
                            index = params.get("index", -1)
                            result = self._create_midi_track(index)
                        elif command_type == "set_track_name":
                            track_index = params.get("track_index", 0)
                            name = params.get("name", "")
                            result = self._set_track_name(track_index, name)
                        elif command_type == "create_clip":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            length = params.get("length", 4.0)
                            result = self._create_clip(track_index, clip_index, length)
                        elif command_type == "add_notes_to_clip":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            notes = params.get("notes", [])
                            result = self._add_notes_to_clip(track_index, clip_index, notes)
                        elif command_type == "set_clip_name":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            name = params.get("name", "")
                            result = self._set_clip_name(track_index, clip_index, name)
                        elif command_type == "set_tempo":
                            tempo = params.get("tempo", 120.0)
                            result = self._set_tempo(tempo)
                        elif command_type == "fire_clip":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            result = self._fire_clip(track_index, clip_index)
                        elif command_type == "stop_clip":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            result = self._stop_clip(track_index, clip_index)
                        elif command_type == "start_playback":
                            result = self._start_playback()
                        elif command_type == "stop_playback":
                            result = self._stop_playback()
                        elif command_type == "load_instrument_or_effect":
                            track_index = params.get("track_index", 0)
                            uri = params.get("uri", "")
                            result = self._load_instrument_or_effect(track_index, uri)
                        elif command_type == "load_browser_item":
                            track_index = params.get("track_index", 0)
                            item_uri = params.get("item_uri", "")
                            result = self._load_browser_item(track_index, item_uri)
                        elif command_type == "create_arrangement_section":
                            section_type = params.get("section_type", "")
                            length_bars = params.get("length_bars", 4)
                            start_bar = params.get("start_bar", -1)
                            result = self._create_arrangement_section(section_type, length_bars, start_bar)
                        elif command_type == "duplicate_section":
                            source_start_bar = params.get("source_start_bar", 0)
                            source_end_bar = params.get("source_end_bar", 4)
                            destination_bar = params.get("destination_bar", 4)
                            variation_level = params.get("variation_level", 0.0)
                            result = self._duplicate_section(source_start_bar, source_end_bar, destination_bar, variation_level)
                        elif command_type == "create_transition":
                            from_bar = params.get("from_bar", 0)
                            to_bar = params.get("to_bar", 0)
                            transition_type = params.get("transition_type", "fill")
                            length_beats = params.get("length_beats", 4)
                            result = self._create_transition(from_bar, to_bar, transition_type, length_beats)
                        elif command_type == "convert_session_to_arrangement":
                            structure = params.get("structure", [])
                            result = self._convert_session_to_arrangement(structure)
                        elif command_type == "set_clip_follow_action_time":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            time_beats = params.get("time_beats", 4.0)
                            result = self._set_clip_follow_action_time(track_index, clip_index, time_beats)
                        elif command_type == "set_clip_follow_action":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            action_type = params.get("action_type", "next")
                            probability = params.get("probability", 1.0)
                            result = self._set_clip_follow_action(track_index, clip_index, action_type, probability)
                        elif command_type == "set_clip_follow_action_linked":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            linked = params.get("linked", True)
                            result = self._set_clip_follow_action_linked(track_index, clip_index, linked)
                        
                        # Put the result in the queue
                        response_queue.put({"status": "success", "result": result})
                    except Exception as e:
                        self.log_message("Error in main thread task: " + str(e))
                        self.log_message(traceback.format_exc())
                        response_queue.put({"status": "error", "message": str(e)})
                
                # Schedule the task to run on the main thread
                try:
                    self.schedule_message(0, main_thread_task)
                except AssertionError:
                    # If we're already on the main thread, execute directly
                    main_thread_task()
                
                # Wait for the response with a timeout
                try:
                    task_response = response_queue.get(timeout=10.0)
                    if task_response.get("status") == "error":
                        response["status"] = "error"
                        response["message"] = task_response.get("message", "Unknown error")
                    else:
                        response["result"] = task_response.get("result", {})
                except queue.Empty:
                    response["status"] = "error"
                    response["message"] = "Timeout waiting for operation to complete"
            elif command_type == "get_browser_item":
                uri = params.get("uri", None)
                path = params.get("path", None)
                response["result"] = self._get_browser_item(uri, path)
            elif command_type == "get_browser_categories":
                category_type = params.get("category_type", "all")
                response["result"] = self._get_browser_categories(category_type)
            elif command_type == "get_browser_items":
                path = params.get("path", "")
                item_type = params.get("item_type", "all")
                response["result"] = self._get_browser_items(path, item_type)
            # Add the new browser commands
            elif command_type == "get_browser_tree":
                category_type = params.get("category_type", "all")
                response["result"] = self.get_browser_tree(category_type)
            elif command_type == "get_browser_items_at_path":
                path = params.get("path", "")
                response["result"] = self.get_browser_items_at_path(path)
            else:
                response["status"] = "error"
                response["message"] = "Unknown command: " + command_type
        except Exception as e:
            self.log_message("Error processing command: " + str(e))
            self.log_message(traceback.format_exc())
            response["status"] = "error"
            response["message"] = str(e)
        
        return response
    
    # Command implementations
    
    def _get_session_info(self):
        """Get information about the current session"""
        try:
            result = {
                "tempo": self._song.tempo,
                "signature_numerator": self._song.signature_numerator,
                "signature_denominator": self._song.signature_denominator,
                "track_count": len(self._song.tracks),
                "return_track_count": len(self._song.return_tracks),
                "master_track": {
                    "name": "Master",
                    "volume": self._song.master_track.mixer_device.volume.value,
                    "panning": self._song.master_track.mixer_device.panning.value
                }
            }
            return result
        except Exception as e:
            self.log_message("Error getting session info: " + str(e))
            raise
    
    def _get_track_info(self, track_index):
        """Get information about a track"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            # Get clip slots
            clip_slots = []
            for slot_index, slot in enumerate(track.clip_slots):
                clip_info = None
                if slot.has_clip:
                    clip = slot.clip
                    clip_info = {
                        "name": clip.name,
                        "length": clip.length,
                        "is_playing": clip.is_playing,
                        "is_recording": clip.is_recording
                    }
                
                clip_slots.append({
                    "index": slot_index,
                    "has_clip": slot.has_clip,
                    "clip": clip_info
                })
            
            # Get devices
            devices = []
            for device_index, device in enumerate(track.devices):
                devices.append({
                    "index": device_index,
                    "name": device.name,
                    "class_name": device.class_name,
                    "type": self._get_device_type(device)
                })
            
            result = {
                "index": track_index,
                "name": track.name,
                "is_audio_track": track.has_audio_input,
                "is_midi_track": track.has_midi_input,
                "mute": track.mute,
                "solo": track.solo,
                "arm": track.arm,
                "volume": track.mixer_device.volume.value,
                "panning": track.mixer_device.panning.value,
                "clip_slots": clip_slots,
                "devices": devices
            }
            return result
        except Exception as e:
            self.log_message("Error getting track info: " + str(e))
            raise
    
    def _create_midi_track(self, index):
        """Create a new MIDI track at the specified index"""
        try:
            # Create the track
            self._song.create_midi_track(index)
            
            # Get the new track
            new_track_index = len(self._song.tracks) - 1 if index == -1 else index
            new_track = self._song.tracks[new_track_index]
            
            result = {
                "index": new_track_index,
                "name": new_track.name
            }
            return result
        except Exception as e:
            self.log_message("Error creating MIDI track: " + str(e))
            raise
    
    
    def _set_track_name(self, track_index, name):
        """Set the name of a track"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            # Set the name
            track = self._song.tracks[track_index]
            track.name = name
            
            result = {
                "name": track.name
            }
            return result
        except Exception as e:
            self.log_message("Error setting track name: " + str(e))
            raise
    
    def _create_clip(self, track_index, clip_index, length):
        """Create a new MIDI clip in the specified track and clip slot"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            
            clip_slot = track.clip_slots[clip_index]
            
            # Check if the clip slot already has a clip
            if clip_slot.has_clip:
                raise Exception("Clip slot already has a clip")
            
            # Create the clip
            clip_slot.create_clip(length)
            
            result = {
                "name": clip_slot.clip.name,
                "length": clip_slot.clip.length
            }
            return result
        except Exception as e:
            self.log_message("Error creating clip: " + str(e))
            raise
    
    def _add_notes_to_clip(self, track_index, clip_index, notes):
        """Add MIDI notes to a clip"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            
            clip_slot = track.clip_slots[clip_index]
            
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            
            clip = clip_slot.clip
            
            # Convert note data to Live's format
            live_notes = []
            for note in notes:
                pitch = note.get("pitch", 60)
                start_time = note.get("start_time", 0.0)
                duration = note.get("duration", 0.25)
                velocity = note.get("velocity", 100)
                mute = note.get("mute", False)
                
                live_notes.append((pitch, start_time, duration, velocity, mute))
            
            # Add the notes
            clip.set_notes(tuple(live_notes))
            
            result = {
                "note_count": len(notes)
            }
            return result
        except Exception as e:
            self.log_message("Error adding notes to clip: " + str(e))
            raise
    
    def _set_clip_name(self, track_index, clip_index, name):
        """Set the name of a clip"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            
            clip_slot = track.clip_slots[clip_index]
            
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            
            clip = clip_slot.clip
            clip.name = name
            
            result = {
                "name": clip.name
            }
            return result
        except Exception as e:
            self.log_message("Error setting clip name: " + str(e))
            raise
    
    def _set_tempo(self, tempo):
        """Set the tempo of the session"""
        try:
            self._song.tempo = tempo
            
            result = {
                "tempo": self._song.tempo
            }
            return result
        except Exception as e:
            self.log_message("Error setting tempo: " + str(e))
            raise
    
    def _fire_clip(self, track_index, clip_index):
        """Fire a clip"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            
            clip_slot = track.clip_slots[clip_index]
            
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            
            clip_slot.fire()
            
            result = {
                "fired": True
            }
            return result
        except Exception as e:
            self.log_message("Error firing clip: " + str(e))
            raise
    
    def _stop_clip(self, track_index, clip_index):
        """Stop a clip"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            
            clip_slot = track.clip_slots[clip_index]
            
            clip_slot.stop()
            
            result = {
                "stopped": True
            }
            return result
        except Exception as e:
            self.log_message("Error stopping clip: " + str(e))
            raise
    
    
    def _start_playback(self):
        """Start playing the session"""
        try:
            self._song.start_playing()
            
            result = {
                "playing": self._song.is_playing
            }
            return result
        except Exception as e:
            self.log_message("Error starting playback: " + str(e))
            raise
    
    def _stop_playback(self):
        """Stop playing the session"""
        try:
            self._song.stop_playing()
            
            result = {
                "playing": self._song.is_playing
            }
            return result
        except Exception as e:
            self.log_message("Error stopping playback: " + str(e))
            raise
    
    def _get_browser_item(self, uri, path):
        """Get a browser item by URI or path"""
        try:
            # Access the application's browser instance instead of creating a new one
            app = self.application()
            if not app:
                raise RuntimeError("Could not access Live application")
                
            result = {
                "uri": uri,
                "path": path,
                "found": False
            }
            
            # Try to find by URI first if provided
            if uri:
                item = self._find_browser_item_by_uri(app.browser, uri)
                if item:
                    result["found"] = True
                    result["item"] = {
                        "name": item.name,
                        "is_folder": item.is_folder,
                        "is_device": item.is_device,
                        "is_loadable": item.is_loadable,
                        "uri": item.uri
                    }
                    return result
            
            # If URI not provided or not found, try by path
            if path:
                # Parse the path and navigate to the specified item
                path_parts = path.split("/")
                
                # Determine the root based on the first part
                current_item = None
                if path_parts[0].lower() == "nstruments":
                    current_item = app.browser.instruments
                elif path_parts[0].lower() == "sounds":
                    current_item = app.browser.sounds
                elif path_parts[0].lower() == "drums":
                    current_item = app.browser.drums
                elif path_parts[0].lower() == "audio_effects":
                    current_item = app.browser.audio_effects
                elif path_parts[0].lower() == "midi_effects":
                    current_item = app.browser.midi_effects
                else:
                    # Default to instruments if not specified
                    current_item = app.browser.instruments
                    # Don't skip the first part in this case
                    path_parts = ["instruments"] + path_parts
                
                # Navigate through the path
                for i in range(1, len(path_parts)):
                    part = path_parts[i]
                    if not part:  # Skip empty parts
                        continue
                    
                    found = False
                    for child in current_item.children:
                        if child.name.lower() == part.lower():
                            current_item = child
                            found = True
                            break
                    
                    if not found:
                        result["error"] = "Path part '{0}' not found".format(part)
                        return result
                
                # Found the item
                result["found"] = True
                result["item"] = {
                    "name": current_item.name,
                    "is_folder": current_item.is_folder,
                    "is_device": current_item.is_device,
                    "is_loadable": current_item.is_loadable,
                    "uri": current_item.uri
                }
            
            return result
        except Exception as e:
            self.log_message("Error getting browser item: " + str(e))
            self.log_message(traceback.format_exc())
            raise   
    
    
    
    def _load_browser_item(self, track_index, item_uri):
        """Load a browser item onto a track by its URI"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            # Access the application's browser instance instead of creating a new one
            app = self.application()
            
            # Find the browser item by URI
            item = self._find_browser_item_by_uri(app.browser, item_uri)
            
            if not item:
                raise ValueError("Browser item with URI '{0}' not found".format(item_uri))
            
            # Select the track
            self._song.view.selected_track = track
            
            # Load the item
            app.browser.load_item(item)
            
            result = {
                "loaded": True,
                "item_name": item.name,
                "track_name": track.name,
                "uri": item_uri
            }
            return result
        except Exception as e:
            self.log_message("Error loading browser item: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise
    
    def _find_browser_item_by_uri(self, browser_or_item, uri, max_depth=10, current_depth=0):
        """Find a browser item by its URI"""
        try:
            # Check if this is the item we're looking for
            if hasattr(browser_or_item, 'uri') and browser_or_item.uri == uri:
                return browser_or_item
            
            # Stop recursion if we've reached max depth
            if current_depth >= max_depth:
                return None
            
            # Check if this is a browser with root categories
            if hasattr(browser_or_item, 'instruments'):
                # Check all main categories
                categories = [
                    browser_or_item.instruments,
                    browser_or_item.sounds,
                    browser_or_item.drums,
                    browser_or_item.audio_effects,
                    browser_or_item.midi_effects
                ]
                
                for category in categories:
                    item = self._find_browser_item_by_uri(category, uri, max_depth, current_depth + 1)
                    if item:
                        return item
                
                return None
            
            # Check if this item has children
            if hasattr(browser_or_item, 'children') and browser_or_item.children:
                for child in browser_or_item.children:
                    item = self._find_browser_item_by_uri(child, uri, max_depth, current_depth + 1)
                    if item:
                        return item
            
            return None
        except Exception as e:
            self.log_message("Error finding browser item by URI: {0}".format(str(e)))
            return None
    
    # Helper methods
    
    def _get_device_type(self, device):
        """Get the type of a device"""
        try:
            # Simple heuristic - in a real implementation you'd look at the device class
            if device.can_have_drum_pads:
                return "drum_machine"
            elif device.can_have_chains:
                return "rack"
            elif "instrument" in device.class_display_name.lower():
                return "instrument"
            elif "audio_effect" in device.class_name.lower():
                return "audio_effect"
            elif "midi_effect" in device.class_name.lower():
                return "midi_effect"
            else:
                return "unknown"
        except:
            return "unknown"
    
    def get_browser_tree(self, category_type="all"):
        """
        Get a simplified tree of browser categories.
        
        Args:
            category_type: Type of categories to get ('all', 'instruments', 'sounds', etc.)
            
        Returns:
            Dictionary with the browser tree structure
        """
        try:
            # Access the application's browser instance instead of creating a new one
            app = self.application()
            if not app:
                raise RuntimeError("Could not access Live application")
                
            # Check if browser is available
            if not hasattr(app, 'browser') or app.browser is None:
                raise RuntimeError("Browser is not available in the Live application")
            
            # Log available browser attributes to help diagnose issues
            browser_attrs = [attr for attr in dir(app.browser) if not attr.startswith('_')]
            self.log_message("Available browser attributes: {0}".format(browser_attrs))
            
            result = {
                "type": category_type,
                "categories": [],
                "available_categories": browser_attrs
            }
            
            # Helper function to process a browser item and its children
            def process_item(item, depth=0):
                if not item:
                    return None
                
                result = {
                    "name": item.name if hasattr(item, 'name') else "Unknown",
                    "is_folder": hasattr(item, 'children') and bool(item.children),
                    "is_device": hasattr(item, 'is_device') and item.is_device,
                    "is_loadable": hasattr(item, 'is_loadable') and item.is_loadable,
                    "uri": item.uri if hasattr(item, 'uri') else None,
                    "children": []
                }
                
                
                return result
            
            # Process based on category type and available attributes
            if (category_type == "all" or category_type == "instruments") and hasattr(app.browser, 'instruments'):
                try:
                    instruments = process_item(app.browser.instruments)
                    if instruments:
                        instruments["name"] = "Instruments"  # Ensure consistent naming
                        result["categories"].append(instruments)
                except Exception as e:
                    self.log_message("Error processing instruments: {0}".format(str(e)))
            
            if (category_type == "all" or category_type == "sounds") and hasattr(app.browser, 'sounds'):
                try:
                    sounds = process_item(app.browser.sounds)
                    if sounds:
                        sounds["name"] = "Sounds"  # Ensure consistent naming
                        result["categories"].append(sounds)
                except Exception as e:
                    self.log_message("Error processing sounds: {0}".format(str(e)))
            
            if (category_type == "all" or category_type == "drums") and hasattr(app.browser, 'drums'):
                try:
                    drums = process_item(app.browser.drums)
                    if drums:
                        drums["name"] = "Drums"  # Ensure consistent naming
                        result["categories"].append(drums)
                except Exception as e:
                    self.log_message("Error processing drums: {0}".format(str(e)))
            
            if (category_type == "all" or category_type == "audio_effects") and hasattr(app.browser, 'audio_effects'):
                try:
                    audio_effects = process_item(app.browser.audio_effects)
                    if audio_effects:
                        audio_effects["name"] = "Audio Effects"  # Ensure consistent naming
                        result["categories"].append(audio_effects)
                except Exception as e:
                    self.log_message("Error processing audio_effects: {0}".format(str(e)))
            
            if (category_type == "all" or category_type == "midi_effects") and hasattr(app.browser, 'midi_effects'):
                try:
                    midi_effects = process_item(app.browser.midi_effects)
                    if midi_effects:
                        midi_effects["name"] = "MIDI Effects"
                        result["categories"].append(midi_effects)
                except Exception as e:
                    self.log_message("Error processing midi_effects: {0}".format(str(e)))
            
            # Try to process other potentially available categories
            for attr in browser_attrs:
                if attr not in ['instruments', 'sounds', 'drums', 'audio_effects', 'midi_effects'] and \
                   (category_type == "all" or category_type == attr):
                    try:
                        item = getattr(app.browser, attr)
                        if hasattr(item, 'children') or hasattr(item, 'name'):
                            category = process_item(item)
                            if category:
                                category["name"] = attr.capitalize()
                                result["categories"].append(category)
                    except Exception as e:
                        self.log_message("Error processing {0}: {1}".format(attr, str(e)))
            
            self.log_message("Browser tree generated for {0} with {1} root categories".format(
                category_type, len(result['categories'])))
            return result
            
        except Exception as e:
            self.log_message("Error getting browser tree: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise
    
    def get_browser_items_at_path(self, path):
        """
        Get browser items at a specific path.
        
        Args:
            path: Path in the format "category/folder/subfolder"
                 where category is one of: instruments, sounds, drums, audio_effects, midi_effects
                 or any other available browser category
                 
        Returns:
            Dictionary with items at the specified path
        """
        try:
            # Access the application's browser instance instead of creating a new one
            app = self.application()
            if not app:
                raise RuntimeError("Could not access Live application")
                
            # Check if browser is available
            if not hasattr(app, 'browser') or app.browser is None:
                raise RuntimeError("Browser is not available in the Live application")
            
            # Log available browser attributes to help diagnose issues
            browser_attrs = [attr for attr in dir(app.browser) if not attr.startswith('_')]
            self.log_message("Available browser attributes: {0}".format(browser_attrs))
                
            # Parse the path
            path_parts = path.split("/")
            if not path_parts:
                raise ValueError("Invalid path")
            
            # Determine the root category
            root_category = path_parts[0].lower()
            current_item = None
            
            # Check standard categories first
            if root_category == "instruments" and hasattr(app.browser, 'instruments'):
                current_item = app.browser.instruments
            elif root_category == "sounds" and hasattr(app.browser, 'sounds'):
                current_item = app.browser.sounds
            elif root_category == "drums" and hasattr(app.browser, 'drums'):
                current_item = app.browser.drums
            elif root_category == "audio_effects" and hasattr(app.browser, 'audio_effects'):
                current_item = app.browser.audio_effects
            elif root_category == "midi_effects" and hasattr(app.browser, 'midi_effects'):
                current_item = app.browser.midi_effects
            else:
                # Try to find the category in other browser attributes
                found = False
                for attr in browser_attrs:
                    if attr.lower() == root_category:
                        try:
                            current_item = getattr(app.browser, attr)
                            found = True
                            break
                        except Exception as e:
                            self.log_message("Error accessing browser attribute {0}: {1}".format(attr, str(e)))
                
                if not found:
                    # If we still haven't found the category, return available categories
                    return {
                        "path": path,
                        "error": "Unknown or unavailable category: {0}".format(root_category),
                        "available_categories": browser_attrs,
                        "items": []
                    }
            
            # Navigate through the path
            for i in range(1, len(path_parts)):
                part = path_parts[i]
                if not part:  # Skip empty parts
                    continue
                
                if not hasattr(current_item, 'children'):
                    return {
                        "path": path,
                        "error": "Item at '{0}' has no children".format('/'.join(path_parts[:i])),
                        "items": []
                    }
                
                found = False
                for child in current_item.children:
                    if hasattr(child, 'name') and child.name.lower() == part.lower():
                        current_item = child
                        found = True
                        break
                
                if not found:
                    return {
                        "path": path,
                        "error": "Path part '{0}' not found".format(part),
                        "items": []
                    }
            
            # Get items at the current path
            items = []
            if hasattr(current_item, 'children'):
                for child in current_item.children:
                    item_info = {
                        "name": child.name if hasattr(child, 'name') else "Unknown",
                        "is_folder": hasattr(child, 'children') and bool(child.children),
                        "is_device": hasattr(child, 'is_device') and child.is_device,
                        "is_loadable": hasattr(child, 'is_loadable') and child.is_loadable,
                        "uri": child.uri if hasattr(child, 'uri') else None
                    }
                    items.append(item_info)
            
            result = {
                "path": path,
                "name": current_item.name if hasattr(current_item, 'name') else "Unknown",
                "uri": current_item.uri if hasattr(current_item, 'uri') else None,
                "is_folder": hasattr(current_item, 'children') and bool(current_item.children),
                "is_device": hasattr(current_item, 'is_device') and current_item.is_device,
                "is_loadable": hasattr(current_item, 'is_loadable') and current_item.is_loadable,
                "items": items
            }
            
            self.log_message("Retrieved {0} items at path: {1}".format(len(items), path))
            return result
            
        except Exception as e:
            self.log_message("Error getting browser items at path: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise

    def _create_arrangement_section(self, section_type, length_bars, start_bar):
        """Create a section in the arrangement (intro, verse, chorus, etc.)"""
        try:
            self.log_message(f"Creating {section_type} section with length {length_bars} bars")
            
            # If start_bar is -1, we add to the end of the arrangement
            if start_bar == -1:
                # Get the end time of the arrangement by finding the latest clip/automation end time
                end_time = 0
                for track in self._song.tracks:
                    for clip in track.arrangement_clips:
                        end_time = max(end_time, clip.end_time)
                
                # Convert to bars (assuming 4/4 time signature)
                beats_per_bar = 4  # Standard 4/4 time signature
                end_bar = int(end_time / beats_per_bar)
                start_bar = end_bar
            
            # Convert bars to time
            beats_per_bar = 4
            start_time = start_bar * beats_per_bar
            
            # Make this a bit more interesting by selecting appropriate clips to include based on section type
            section_tracks = {}
            
            # Different clip selection strategies based on section type
            if section_type.lower() == "intro":
                # For intro, focus on simpler elements
                section_tracks = self._select_clips_for_section("intro")
            elif section_type.lower() == "verse":
                section_tracks = self._select_clips_for_section("verse")
            elif section_type.lower() == "chorus":
                section_tracks = self._select_clips_for_section("chorus")
            elif section_type.lower() == "bridge":
                section_tracks = self._select_clips_for_section("bridge")
            elif section_type.lower() == "outro":
                section_tracks = self._select_clips_for_section("outro")
            else:
                # For unrecognized sections, just use all tracks
                section_tracks = self._select_clips_for_section("generic")
            
            # Now create clips in the arrangement for each track
            for track_index, clip_indices in section_tracks.items():
                if track_index >= len(self._song.tracks):
                    continue
                
                track = self._song.tracks[track_index]
                
                for clip_index in clip_indices:
                    if clip_index >= len(track.clip_slots) or not track.clip_slots[clip_index].has_clip:
                        continue
                    
                    clip_slot = track.clip_slots[clip_index]
                    source_clip = clip_slot.clip
                    
                    # Calculate how many times to loop this clip to fill the section
                    section_length = length_bars * beats_per_bar
                    clip_repeats = int(section_length / source_clip.length) + 1  # +1 to ensure we fill the section
                    
                    # For each repeat, create a copy of the clip in the arrangement
                    for i in range(clip_repeats):
                        # Calculate position for this repetition
                        rep_start_time = start_time + (i * source_clip.length)
                        
                        # If this repetition would extend past the section, skip it
                        if rep_start_time >= start_time + section_length:
                            break
                        
                        # Add to arrangement at the calculated position
                        source_clip.duplicate_clip_to(track, rep_start_time)
            
            result = {
                "section_type": section_type,
                "start_position": start_bar,
                "length_bars": length_bars
            }
            return result
            
        except Exception as e:
            self.log_message(f"Error creating arrangement section: {str(e)}")
            self.log_message(traceback.format_exc())
            raise

    def _select_clips_for_section(self, section_type):
        """Helper function to select appropriate clips for a section type"""
        tracks = {}
        
        # For now, implement a simple strategy based on section type
        if section_type == "intro":
            # For intro, use fewer tracks, focus on foundational elements
            drum_track_found = False
            bass_track_found = False
            
            for i, track in enumerate(self._song.tracks):
                # Simple heuristic to find drum and bass tracks based on name
                if not drum_track_found and "drum" in track.name.lower():
                    # For drums, choose a clip that appears to be a basic pattern
                    clips = [j for j, slot in enumerate(track.clip_slots) if slot.has_clip]
                    if clips:
                        tracks[i] = [clips[0]]  # Just use the first clip for simplicity
                        drum_track_found = True
                
                elif not bass_track_found and "bass" in track.name.lower():
                    # For bass, choose a clip that appears to be a basic pattern
                    clips = [j for j, slot in enumerate(track.clip_slots) if slot.has_clip]
                    if clips:
                        tracks[i] = [clips[0]]  # Just use the first clip for simplicity
                        bass_track_found = True
        
        elif section_type == "chorus":
            # For chorus, use most available tracks for a fuller sound
            for i, track in enumerate(self._song.tracks):
                clips = [j for j, slot in enumerate(track.clip_slots) if slot.has_clip]
                if clips:
                    # Try to find clips that appear to be more energetic
                    # (in real implementation, this would use more sophisticated analysis)
                    tracks[i] = [clips[-1] if len(clips) > 1 else clips[0]]
        
        else:
            # Default strategy: use any available clips
            for i, track in enumerate(self._song.tracks):
                clips = [j for j, slot in enumerate(track.clip_slots) if slot.has_clip]
                if clips:
                    tracks[i] = [clips[0]]  # Just use the first clip for simplicity
        
        return tracks

    def _duplicate_section(self, source_start_bar, source_end_bar, destination_bar, variation_level):
        """Duplicate a section of the arrangement with optional variations"""
        try:
            self.log_message(f"Duplicating section from bar {source_start_bar} to {source_end_bar}")
            
            # Convert bars to time
            beats_per_bar = 4  # Standard 4/4 time signature
            source_start_time = source_start_bar * beats_per_bar
            source_end_time = source_end_bar * beats_per_bar
            destination_time = destination_bar * beats_per_bar
            
            # Get all clips in the source range
            section_length = source_end_time - source_start_time
            
            # For each track, find clips in the source range and duplicate them
            for track in self._song.tracks:
                # Get clips that overlap with the source range
                for clip in track.arrangement_clips:
                    # Check if clip overlaps with source range
                    if clip.start_time < source_end_time and clip.end_time > source_start_time:
                        # Calculate clip position relative to section start
                        clip_rel_start = max(0, clip.start_time - source_start_time)
                        
                        # Calculate new start time in destination
                        new_start_time = destination_time + clip_rel_start
                        
                        # Duplicate the clip to the new position
                        clip.duplicate_clip_to(track, new_start_time)
                        
                        # If variation level > 0, apply variations to the new clip
                        if variation_level > 0:
                            # Find the newly created clip - it should be the last one added
                            new_clip = None
                            for c in track.arrangement_clips:
                                if c.start_time == new_start_time:
                                    new_clip = c
                                    break
                            
                            if new_clip and new_clip.is_midi_clip:
                                self._apply_variations(new_clip, variation_level)
            
            result = {
                "source_start_bar": source_start_bar,
                "source_end_bar": source_end_bar,
                "destination_bar": destination_bar,
                "variation_level": variation_level
            }
            return result
            
        except Exception as e:
            self.log_message(f"Error duplicating section: {str(e)}")
            self.log_message(traceback.format_exc())
            raise

    def _apply_variations(self, clip, variation_level):
        """Apply variations to a MIDI clip based on variation level"""
        try:
            if not clip.is_midi_clip:
                return
            
            # Get the notes from the clip
            notes = list(clip.get_notes(0, 0, clip.length, 127))
            
            # Skip if no notes
            if not notes:
                return
            
            # Apply variations based on level
            if variation_level > 0.8:
                # High variation: significantly change pattern
                new_notes = []
                for note in notes:
                    # Keep some notes, modify others, add new ones
                    if random.random() > 0.3:  # Keep 70% of original notes
                        # Possibly modify pitch
                        pitch = note[0]
                        if random.random() < 0.4:  # 40% chance to change pitch
                            pitch = max(0, min(127, pitch + random.choice([-2, -1, 1, 2])))
                        
                        # Possibly modify timing
                        start = note[1]
                        if random.random() < 0.3:  # 30% chance to shift timing
                            start = max(0, min(clip.length, start + random.uniform(-0.125, 0.125)))
                        
                        new_notes.append((pitch, start, note[2], note[3], note[4]))
                    
                    # 20% chance to add a new note
                    if random.random() < 0.2:
                        # Create a new note based on this one
                        pitch = max(0, min(127, note[0] + random.choice([-12, -7, -5, 0, 5, 7, 12])))
                        start = max(0, min(clip.length, note[1] + random.uniform(-0.25, 0.25)))
                        duration = note[2]
                        velocity = note[3]
                        new_notes.append((pitch, start, duration, velocity, False))
                
                # Replace notes
                clip.set_notes(tuple(new_notes))
                
            elif variation_level > 0.5:
                # Medium variation: modify some notes, keep structure
                new_notes = []
                for note in notes:
                    # 80% chance to keep note, 20% to modify
                    if random.random() < 0.8:
                        new_notes.append(note)
                    else:
                        # Modify pitch
                        pitch = max(0, min(127, note[0] + random.choice([-1, 1])))
                        
                        # Modify timing slightly
                        start = max(0, min(clip.length, note[1] + random.uniform(-0.05, 0.05)))
                        
                        new_notes.append((pitch, start, note[2], note[3], note[4]))
                
                # Replace notes
                clip.set_notes(tuple(new_notes))
                
            elif variation_level > 0.2:
                # Low variation: subtle changes
                new_notes = []
                for note in notes:
                    # 90% chance to keep the same, 10% to modify velocity
                    if random.random() < 0.9:
                        new_notes.append(note)
                    else:
                        # Modify velocity slightly
                        velocity = max(1, min(127, int(note[3] + random.uniform(-10, 10))))
                        
                        new_notes.append((note[0], note[1], note[2], velocity, note[4]))
                
                # Replace notes
                clip.set_notes(tuple(new_notes))
                
        except Exception as e:
            self.log_message(f"Error applying variations: {str(e)}")
    
    def _create_transition(self, from_bar, to_bar, transition_type, length_beats):
        """Create a transition between two sections"""
        try:
            self.log_message(f"Creating {transition_type} transition from bar {from_bar} to bar {to_bar}")
            
            # Convert bars to time
            beats_per_bar = 4  # Standard 4/4 time signature
            from_time = from_bar * beats_per_bar
            to_time = to_bar * beats_per_bar
            
            # Find a suitable track for the transition
            # Transitions typically involve drums and/or effects
            drum_track = None
            for i, track in enumerate(self._song.tracks):
                if "drum" in track.name.lower():
                    drum_track = track
                    break
            
            # If no drum track was found, use the first track
            if drum_track is None and len(self._song.tracks) > 0:
                drum_track = self._song.tracks[0]
            
            # No tracks available
            if drum_track is None:
                raise Exception("No tracks available for creating transition")
            
            # Create transition based on type
            if transition_type.lower() == "fill":
                # Create a drum fill at the end of the section
                fill_start_time = to_time - (length_beats * 0.25)  # Start a bit before the target bar
                
                # Find a clip to use as template for the fill
                template_clip = None
                for slot in drum_track.clip_slots:
                    if slot.has_clip:
                        template_clip = slot.clip
                        break
                
                if template_clip and template_clip.is_midi_clip:
                    # Create new clip in arrangement
                    new_clip = drum_track.create_clip(fill_start_time, length_beats * 0.25)
                    
                    # Copy notes from template
                    template_notes = list(template_clip.get_notes(0, 0, template_clip.length, 127))
                    
                    # Modify notes to create a fill pattern (more dense at the end)
                    fill_notes = []
                    for i, note in enumerate(template_notes):
                        # Keep original pitch but adjust timing to create a fill pattern
                        pitch = note[0]
                        
                        # Create a pattern with increasing density
                        new_time = (i % 4) * 0.125
                        duration = 0.125  # Sixteenth note
                        
                        # Higher velocity for accents
                        velocity = 100 if i % 4 == 0 else 80
                        
                        fill_notes.append((pitch, new_time, duration, velocity, False))
                    
                    # Add extra notes at end of fill for buildup
                    for i in range(4):
                        pitch = 38  # Snare drum
                        new_time = length_beats * 0.25 - 0.25 + (i * 0.0625)  # Last quarter note
                        duration = 0.0625  # Thirty-second note
                        velocity = 100 + (i * 10)  # Increasing velocity
                        
                        fill_notes.append((pitch, new_time, duration, velocity, False))
                    
                    # Set notes in the new clip
                    new_clip.set_notes(tuple(fill_notes))
            
            elif transition_type.lower() in ["riser", "uplifter"]:
                # Create a riser effect before the target bar
                riser_start_time = to_time - length_beats
                
                # Look for an effect track
                effect_track = None
                for track in self._song.tracks:
                    if "fx" in track.name.lower() or "effect" in track.name.lower():
                        effect_track = track
                        break
                
                # If no effect track, use the drum track
                if effect_track is None:
                    effect_track = drum_track
                
                # Create automation for a parameter (e.g., filter cutoff)
                # This is a simplified implementation - in a real scenario, you'd
                # find a device and automate specific parameters
                for device in effect_track.devices:
                    # Find a filterable parameter to automate
                    for parameter in device.parameters:
                        if "cutoff" in parameter.name.lower() or "freq" in parameter.name.lower():
                            # Create automation that rises from min to max
                            parameter.automation_state = 1  # Enable automation
                            parameter.add_automation_point(riser_start_time, parameter.min)
                            parameter.add_automation_point(to_time, parameter.max)
                            break
            
            elif transition_type.lower() == "cut":
                # Simple cut - stop all clips just before the target bar
                cut_time = to_time - 0.01
                for track in self._song.tracks:
                    for clip in track.arrangement_clips:
                        if clip.start_time < to_time and clip.end_time > cut_time:
                            # Trim the clip end to create a cut
                            clip.end_time = cut_time
            
            result = {
                "transition_type": transition_type,
                "from_bar": from_bar,
                "to_bar": to_bar,
                "length_beats": length_beats
            }
            return result
            
        except Exception as e:
            self.log_message(f"Error creating transition: {str(e)}")
            self.log_message(traceback.format_exc())
            raise
    
    def _convert_session_to_arrangement(self, structure):
        """Convert session clips to arrangement based on a specified structure"""
        try:
            self.log_message(f"Converting session to arrangement with structure: {structure}")
            
            # Clear the arrangement view first
            self._song.clear_arrangement()
            
            current_bar = 0
            
            # Process each section in the structure
            for section in structure:
                section_type = section.get("type", "generic")
                length_bars = section.get("length_bars", 4)
                
                # Create a section at the current position
                self._create_arrangement_section(section_type, length_bars, current_bar)
                
                # If more than one section, create a transition between them
                if current_bar > 0:
                    # Choose transition type based on what sections are being connected
                    transition_type = "fill"  # Default
                    
                    # Update transition type based on the sections being connected
                    prev_section_type = structure[structure.index(section) - 1].get("type", "generic")
                    if prev_section_type == "verse" and section_type == "chorus":
                        transition_type = "riser"
                    elif prev_section_type == "chorus" and section_type == "verse":
                        transition_type = "downlifter"
                    elif prev_section_type == "chorus" and section_type == "bridge":
                        transition_type = "cut"
                    
                    # Create the transition
                    self._create_transition(current_bar - 1, current_bar, transition_type, 4)
                
                # Move to the next position
                current_bar += length_bars
            
            result = {
                "total_length_bars": current_bar,
                "section_count": len(structure)
            }
            return result
            
        except Exception as e:
            self.log_message(f"Error converting session to arrangement: {str(e)}")
            self.log_message(traceback.format_exc())
            raise

    def _set_clip_follow_action_time(self, track_index, clip_index, time_beats):
        """Set the follow action time for a clip in beats"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            
            clip_slot = track.clip_slots[clip_index]
            
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            
            # Set the follow action time
            clip_slot.clip.follow_action_time = time_beats
            
            result = {
                "track_index": track_index,
                "clip_index": clip_index,
                "follow_action_time": clip_slot.clip.follow_action_time
            }
            return result
        except Exception as e:
            self.log_message(f"Error setting clip follow action time: {str(e)}")
            raise
    
    def _set_clip_follow_action(self, track_index, clip_index, action_type, probability):
        """Set the follow action for a clip"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            
            clip_slot = track.clip_slots[clip_index]
            
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            
            clip = clip_slot.clip
            
            # Map action_type string to the appropriate value
            # Common follow actions: "none", "next", "prev", "first", "last", "any", "other"
            action_map = {
                "none": 0,
                "next": 1,
                "prev": 2,
                "first": 3,
                "last": 4,
                "any": 5,
                "other": 6
            }
            
            # Set default to "none" if not recognized
            action_value = action_map.get(action_type.lower(), 0)
            
            # Validate probability (0.0 to 1.0)
            probability = max(0.0, min(1.0, probability))
            
            # For action A (primary action)
            clip.follow_action_a = action_value
            clip.follow_action_a_probability = probability
            
            # For action B (secondary action) - set to none with remaining probability
            # When A has 100% probability, B is never used
            clip.follow_action_b = 0  # None
            clip.follow_action_b_probability = 1.0 - probability
            
            # Enable follow actions
            clip.follow_action_enabled = True
            
            result = {
                "track_index": track_index,
                "clip_index": clip_index,
                "action_type": action_type,
                "probability": probability,
                "follow_action_enabled": clip.follow_action_enabled
            }
            return result
        except Exception as e:
            self.log_message(f"Error setting clip follow action: {str(e)}")
            raise
    
    def _set_clip_follow_action_linked(self, track_index, clip_index, linked):
        """Set whether the follow action timing is linked to the clip length"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            
            clip_slot = track.clip_slots[clip_index]
            
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            
            clip = clip_slot.clip
            
            # Set the follow action linked state
            clip.follow_action_follow_time_linked = linked
            
            result = {
                "track_index": track_index,
                "clip_index": clip_index,
                "linked": clip.follow_action_follow_time_linked
            }
            return result
        except Exception as e:
            self.log_message(f"Error setting clip follow action linked: {str(e)}")
            raise
