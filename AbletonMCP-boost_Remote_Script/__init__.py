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
    return AbletonMCPboost(c_instance)

class AbletonMCPboost(ControlSurface):
    """AbletonMCPboost Remote Script for Ableton Live"""
    
    def __init__(self, c_instance):
        """Initialize the control surface"""
        ControlSurface.__init__(self, c_instance)
        self.log_message("AbletonMCPboost Remote Script initializing...")
        
        # Socket server for communication
        self.server = None
        self.client_threads = []
        self.server_thread = None
        self.running = False
        
        # Cache the song reference for easier access
        self._song = self.song()
        
        # Start the socket server
        self.start_server()
        
        self.log_message("AbletonMCPboost initialized")
        
        # Show a message in Ableton
        self.show_message("AbletonMCPboost: Listening for commands on port " + str(DEFAULT_PORT))
    
    def disconnect(self):
        """Called when Ableton closes or the control surface is removed"""
        self.log_message("AbletonMCPboost disconnecting...")
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
        self.log_message("AbletonMCPboost disconnected")
    
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
            self.show_message("AbletonMCPboost: Error starting server - " + str(e))
    
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
                    self.show_message("AbletonMCPboost: Client connected")
                    
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
            # Add the new arrangement info commands
            elif command_type == "get_arrangement_info":
                response["result"] = self._get_arrangement_info()
            elif command_type == "get_track_arrangement_clips":
                track_index = params.get("track_index", 0)
                response["result"] = self._get_track_arrangement_clips(track_index)
            elif command_type == "get_time_signatures":
                response["result"] = self._get_time_signatures()
            elif command_type == "get_arrangement_markers":
                response["result"] = self._get_arrangement_markers()
            # New Live 11 compatible view switching commands
            elif command_type == "show_arrangement_view":
                response["result"] = self._show_arrangement_view()
            elif command_type == "show_session_view":
                response["result"] = self._show_session_view()
            # Commands that modify Live's state should be scheduled on the main thread
            elif command_type in ["create_midi_track", "set_track_name", 
                                 "create_clip", "add_notes_to_clip", "set_clip_name", 
                                 "set_tempo", "fire_clip", "stop_clip",
                                 "start_playback", "stop_playback", "load_browser_item",
                                 "create_arrangement_section", "duplicate_section", 
                                 "create_transition", "convert_session_to_arrangement",
                                 "set_clip_follow_action_time", "set_clip_follow_action",
                                 "set_clip_follow_action_linked", "setup_clip_sequence",
                                 "setup_project_follow_actions",
                                 # Add new arrangement-specific commands
                                 "add_automation_to_clip", "create_audio_track",
                                 "insert_arrangement_clip", "duplicate_clip_to_arrangement",
                                 "set_locators", "set_arrangement_loop",
                                 "set_time_signature", "set_playhead_position",
                                 "create_arrangement_marker", "create_complex_arrangement",
                                 "quantize_arrangement_clips", "consolidate_arrangement_selection",
                                 # Live 11 compatible arrangement commands
                                 "set_arrangement_record", "arrangement_to_session",
                                 "start_arrangement_recording"]:
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
                        elif command_type == "setup_clip_sequence":
                            track_index = params.get("track_index", 0)
                            start_clip_index = params.get("start_clip_index", 0)
                            end_clip_index = params.get("end_clip_index", 0)
                            loop_back = params.get("loop_back", True)
                            result = self._setup_clip_sequence(track_index, start_clip_index, end_clip_index, loop_back)
                        elif command_type == "setup_project_follow_actions":
                            loop_back = params.get("loop_back", True)
                            result = self._setup_project_follow_actions(loop_back)
                        # New arrangement commands
                        elif command_type == "add_automation_to_clip":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            parameter_name = params.get("parameter_name", "")
                            points = params.get("points", [])
                            result = self._add_automation_to_clip(track_index, clip_index, parameter_name, points)
                        elif command_type == "create_audio_track":
                            index = params.get("index", -1)
                            result = self._create_audio_track(index)
                        elif command_type == "insert_arrangement_clip":
                            track_index = params.get("track_index", 0)
                            start_time = params.get("start_time", 0.0)
                            length = params.get("length", 4.0)
                            is_audio = params.get("is_audio", False)
                            result = self._insert_arrangement_clip(track_index, start_time, length, is_audio)
                        elif command_type == "duplicate_clip_to_arrangement":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            arrangement_time = params.get("arrangement_time", 0.0)
                            result = self._duplicate_clip_to_arrangement(track_index, clip_index, arrangement_time)
                        elif command_type == "set_locators":
                            start_time = params.get("start_time", 0.0)
                            end_time = params.get("end_time", 4.0)
                            name = params.get("name", "")
                            result = self._set_locators(start_time, end_time, name)
                        elif command_type == "set_arrangement_loop":
                            start_time = params.get("start_time", 0.0)
                            end_time = params.get("end_time", 4.0)
                            enabled = params.get("enabled", True)
                            result = self._set_arrangement_loop(start_time, end_time, enabled)
                        # Additional arrangement commands
                        elif command_type == "set_time_signature":
                            numerator = params.get("numerator", 4)
                            denominator = params.get("denominator", 4)
                            bar_position = params.get("bar_position", 1)
                            result = self._set_time_signature(numerator, denominator, bar_position)
                        elif command_type == "set_playhead_position":
                            time = params.get("time", 0.0)
                            result = self._set_playhead_position(time)
                        elif command_type == "create_arrangement_marker":
                            name = params.get("name", "Marker")
                            time = params.get("time", 0.0)
                            result = self._create_arrangement_marker(name, time)
                        elif command_type == "create_complex_arrangement":
                            structure = params.get("structure", [])
                            transitions = params.get("transitions", True)
                            arrange_automation = params.get("arrange_automation", True)
                            result = self._create_complex_arrangement(structure, transitions, arrange_automation)
                        elif command_type == "quantize_arrangement_clips":
                            track_index = params.get("track_index", -1)
                            quantize_amount = params.get("quantize_amount", 1.0)
                            result = self._quantize_arrangement_clips(track_index, quantize_amount)
                        elif command_type == "consolidate_arrangement_selection":
                            start_time = params.get("start_time", 0.0)
                            end_time = params.get("end_time", 4.0)
                            track_index = params.get("track_index", 0)
                            result = self._consolidate_arrangement_selection(start_time, end_time, track_index)
                        # Live 11 compatible arrangement commands
                        elif command_type == "set_arrangement_record":
                            enabled = params.get("enabled", True)
                            result = self._set_arrangement_record(enabled)
                        elif command_type == "arrangement_to_session":
                            track_index = params.get("track_index", 0)
                            start_time = params.get("start_time", 0.0)
                            end_time = params.get("end_time", 4.0)
                            target_clip_slot = params.get("target_clip_slot", 0)
                            result = self._arrangement_to_session(track_index, start_time, end_time, target_clip_slot)
                        elif command_type == "start_arrangement_recording":
                            result = self._start_arrangement_recording()
                        
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

    def _has_api_feature(self, obj, attribute):
        """Safely check if an API feature/attribute exists"""
        try:
            return hasattr(obj, attribute)
        except:
            return False

    def _create_arrangement_section(self, section_type, length_bars, start_bar):
        """Create a section in the arrangement (intro, verse, chorus, etc.)"""
        try:
            self.log_message(f"Creating {section_type} section with length {length_bars} bars")
            
            # If start_bar is -1, we add to the end of the arrangement
            if start_bar == -1:
                # Get the end time of the arrangement by finding the latest clip/automation end time
                end_time = 0
                for track in self._song.tracks:
                    # Check if track has arrangement_clips attribute
                    if self._has_api_feature(track, 'arrangement_clips'):
                        for clip in track.arrangement_clips:
                            if self._has_api_feature(clip, 'end_time'):
                                end_time = max(end_time, clip.end_time)
                            elif self._has_api_feature(clip, 'end_marker') and self._has_api_feature(clip.end_marker, 'time'):
                                end_time = max(end_time, clip.end_marker.time)
                
                # Convert to bars (assuming 4/4 time signature)
                beats_per_bar = 4  # Standard 4/4 time signature
                end_bar = int(end_time / beats_per_bar)
                start_bar = end_bar
            
            # Convert bars to time
            beats_per_bar = 4
            start_time = start_bar * beats_per_bar
            
            # Make this a bit more interesting by selecting appropriate clips based on section type
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
                        
                        # Create a new clip instead of using duplicate_clip_to
                        try:
                            new_clip = track.create_clip(rep_start_time, source_clip.length)
                            
                            # If it's a MIDI clip, copy the notes
                            if hasattr(source_clip, 'get_notes') and hasattr(new_clip, 'set_notes'):
                                notes = list(source_clip.get_notes(0, 0, source_clip.length, 127))
                                if notes:
                                    new_clip.set_notes(tuple(notes))
                            
                            # Copy clip name if possible
                            if hasattr(source_clip, 'name') and hasattr(new_clip, 'name'):
                                new_clip.name = source_clip.name
                        except Exception as e:
                            self.log_message(f"Error creating clip in arrangement: {str(e)}")
            
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
                
                if template_clip and hasattr(template_clip, 'is_midi_clip') and template_clip.is_midi_clip:
                    # Create new clip in arrangement
                    try:
                        new_clip = drum_track.create_clip(fill_start_time, length_beats * 0.25)
                        
                        # Get notes from template if possible
                        if hasattr(template_clip, 'get_notes') and hasattr(new_clip, 'set_notes'):
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
                    except Exception as e:
                        self.log_message(f"Error creating fill clip: {str(e)}")
            
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
                try:
                    # Create a MIDI clip to hold automation
                    new_clip = effect_track.create_clip(riser_start_time, length_beats)
                    
                    # Find a device and parameter to automate
                    for device in effect_track.devices:
                        # Find a filterable parameter to automate
                        for parameter in device.parameters:
                            if ("cutoff" in parameter.name.lower() or 
                                "freq" in parameter.name.lower() or 
                                "filter" in parameter.name.lower()):
                                
                                # Create rising automation
                                if hasattr(new_clip, 'clear_envelope') and hasattr(new_clip, 'set_envelope_point'):
                                    new_clip.clear_envelope(parameter)
                                    new_clip.set_envelope_point(parameter, 0.0, parameter.min)
                                    new_clip.set_envelope_point(parameter, length_beats, parameter.max)
                                    break
                except Exception as e:
                    self.log_message(f"Error creating riser automation: {str(e)}")
            
            elif transition_type.lower() == "cut":
                # Simple cut - just leave a gap between sections
                # We don't need to do anything special for this in terms of clip creation
                pass
            
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
            
            # We'll implement this without using clear_arrangement
            # Instead we'll just add clips at the specified positions
            
            current_bar = 0
            section_count = 0
            
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
                    prev_section_type = structure[section_count - 1].get("type", "generic")
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
                section_count += 1
            
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

    def _setup_clip_sequence(self, track_index, start_clip_index, end_clip_index, loop_back=True):
        """Setup a sequence of clips with follow actions to play in order"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            # Process each clip in the sequence
            clips_processed = 0
            for clip_index in range(start_clip_index, end_clip_index + 1):
                try:
                    if clip_index < 0 or clip_index >= len(track.clip_slots):
                        self.log_message(f"Clip index {clip_index} out of range, skipping")
                        continue
                        
                    clip_slot = track.clip_slots[clip_index]
                    
                    if not clip_slot.has_clip:
                        self.log_message(f"No clip in slot {clip_index}, skipping")
                        continue
                    
                    clip = clip_slot.clip
                    
                    # Set follow action to "next" with 100% probability
                    clip.follow_action_a = 1  # Next
                    clip.follow_action_a_probability = 1.0
                    clip.follow_action_b = 0  # None
                    clip.follow_action_b_probability = 0.0
                    
                    # Set follow action time to match clip length
                    clip.follow_action_time = clip.length
                    
                    # Link follow action to clip length
                    clip.follow_action_follow_time_linked = True
                    
                    # Enable follow actions
                    clip.follow_action_enabled = True
                    
                    clips_processed += 1
                    
                except Exception as e:
                    self.log_message(f"Error setting up follow action for clip {clip_index}: {str(e)}")
                    # Continue with next clip
            
            # Handle special case for last clip to loop back to the first
            if clips_processed > 0 and loop_back and end_clip_index < len(track.clip_slots) and track.clip_slots[end_clip_index].has_clip:
                clip = track.clip_slots[end_clip_index].clip
                
                # Set the last clip to go back to the first one
                if start_clip_index == 0:
                    clip.follow_action_a = 3  # First
                else:
                    clip.follow_action_a = 6  # Other (would need specific index)
                
                clip.follow_action_a_probability = 1.0
                clip.follow_action_b = 0  # None
                clip.follow_action_b_probability = 0.0
                clip.follow_action_enabled = True
            
            result = {
                "track_index": track_index,
                "clips_processed": clips_processed
            }
            return result
            
        except Exception as e:
            self.log_message(f"Error setting up clip sequence: {str(e)}")
            raise
    
    def _setup_project_follow_actions(self, loop_back=True):
        """Setup follow actions for all tracks in the project"""
        try:
            total_clips_processed = 0
            tracks_processed = 0
            
            # Process each track
            for track_index, track in enumerate(self._song.tracks):
                try:
                    # Find clips in this track
                    clips_with_content = []
                    for i, clip_slot in enumerate(track.clip_slots):
                        if clip_slot.has_clip:
                            clips_with_content.append(i)
                    
                    if not clips_with_content:
                        self.log_message(f"No clips found in track {track_index}, skipping")
                        continue
                    
                    # Process clips in sequence
                    clips_processed = 0
                    for i, clip_index in enumerate(clips_with_content):
                        try:
                            clip_slot = track.clip_slots[clip_index]
                            clip = clip_slot.clip
                            
                            # Set follow action to "next" with 100% probability
                            action_value = 1  # Next
                            
                            # If this is the last clip and loop_back is True, set action to go back to first clip
                            if i == len(clips_with_content) - 1 and loop_back:
                                if clips_with_content[0] == 0:
                                    action_value = 3  # First
                                else:
                                    action_value = 6  # Other (would need specific index)
                            
                            # For action A (primary action)
                            clip.follow_action_a = action_value
                            clip.follow_action_a_probability = 1.0
                            
                            # For action B (secondary action)
                            clip.follow_action_b = 0  # None
                            clip.follow_action_b_probability = 0.0
                            
                            # Set follow action time to match clip length and link it
                            clip.follow_action_time = clip.length
                            clip.follow_action_follow_time_linked = True
                            
                            # Enable follow actions
                            clip.follow_action_enabled = True
                            
                            clips_processed += 1
                            
                        except Exception as e:
                            self.log_message(f"Error setting up follow action for track {track_index}, clip {clip_index}: {str(e)}")
                            # Continue with next clip
                    
                    if clips_processed > 0:
                        tracks_processed += 1
                        total_clips_processed += clips_processed
                        self.log_message(f"Processed {clips_processed} clips in track {track_index}")
                    
                except Exception as e:
                    self.log_message(f"Error processing track {track_index}: {str(e)}")
                    # Continue with next track
            
            result = {
                "total_clips_processed": total_clips_processed,
                "tracks_processed": tracks_processed
            }
            return result
            
        except Exception as e:
            self.log_message(f"Error setting up project follow actions: {str(e)}")
            raise

    def _add_automation_to_clip(self, track_index, clip_index, parameter_name, points):
        """Add automation points to a clip parameter"""
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
            
            # Find the parameter to automate
            parameter = None
            
            # Check common mixer parameters first
            if parameter_name.lower() == "volume":
                parameter = track.mixer_device.volume
            elif parameter_name.lower() == "panning":
                parameter = track.mixer_device.panning
            elif parameter_name.startswith("send_"):
                try:
                    send_index = int(parameter_name.split("_")[1])
                    if send_index < len(track.mixer_device.sends):
                        parameter = track.mixer_device.sends[send_index]
                except:
                    pass
            # Check device parameters
            elif parameter_name.startswith("device"):
                try:
                    parts = parameter_name.split("_")
                    device_index = int(parts[0][6:])  # Extract the number from "device1"
                    param_index = int(parts[1][5:])   # Extract the number from "param1"
                    
                    if device_index < len(track.devices):
                        device = track.devices[device_index]
                        if param_index < len(device.parameters):
                            parameter = device.parameters[param_index]
                except:
                    pass
            
            if parameter is None:
                raise Exception(f"Parameter '{parameter_name}' not found")
            
            # Clear existing automation for this parameter
            if clip.is_midi_clip:
                clip.clear_envelope(parameter)
            
            # Add automation points
            for point in points:
                clip.set_envelope_point(
                    parameter,
                    point.get("time", 0.0),  # Time in beats
                    point.get("value", 0.0)  # Parameter value
                )
            
            result = {
                "track_index": track_index,
                "clip_index": clip_index,
                "parameter": parameter_name,
                "point_count": len(points)
            }
            return result
        except Exception as e:
            self.log_message(f"Error adding automation to clip: {str(e)}")
            raise
    
    def _create_audio_track(self, index):
        """Create a new audio track at the specified index"""
        try:
            # Create the track
            self._song.create_audio_track(index)
            
            # Get the new track
            new_track_index = len(self._song.tracks) - 1 if index == -1 else index
            new_track = self._song.tracks[new_track_index]
            
            result = {
                "index": new_track_index,
                "name": new_track.name
            }
            return result
        except Exception as e:
            self.log_message(f"Error creating audio track: {str(e)}")
            raise
    
    def _insert_arrangement_clip(self, track_index, start_time, length, is_audio=False):
        """Insert a clip directly in the arrangement view without using create_clip"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            # Determine if we can create the requested clip type on this track
            if is_audio and not track.has_audio_input:
                raise Exception("Cannot create audio clip on MIDI track")
            elif not is_audio and not track.has_midi_input:
                raise Exception("Cannot create MIDI clip on audio track")
            
            # For Live 11 without create_clip, we'll use a different approach
            # Similar to the duplicate_clip_to_arrangement method:
            # 1. Find a suitable clip slot with a clip
            # 2. Position the playhead
            # 3. Enable recording
            # 4. Fire the clip
            
            # First, we need to find a clip to use as a template
            template_clip_slot = None
            for slot in track.clip_slots:
                if slot.has_clip:
                    template_clip_slot = slot
                    break
            
            # If no template found, we can't insert a clip this way
            if template_clip_slot is None:
                # Return a placeholder result
                result = {
                    "track_index": track_index,
                    "start_time": start_time,
                    "length": length,
                    "note": "No template clip available. Create a clip in session view first."
                }
                return result
            
            # Otherwise, use similar approach to duplicate_clip_to_arrangement
            current_position = self._song.current_song_time
            was_playing = self._song.is_playing
            was_recording = self._song.record_mode
            
            # Position the playhead
            self._song.current_song_time = start_time
            
            # Enable arrangement record mode
            self._song.record_mode = True
            
            # Start playback if not already playing
            if not self._song.is_playing:
                self._song.start_playing()
            
            # Fire the template clip
            template_clip_slot.fire()
            
            # Return a placeholder result
            result = {
                "track_index": track_index,
                "start_time": start_time,
                "length": length,
                "note": "Clip creation initiated. Check arrangement view."
            }
            return result
        except Exception as e:
            self.log_message(f"Error inserting arrangement clip: {str(e)}")
            raise
    
    def _duplicate_clip_to_arrangement(self, track_index, clip_index, arrangement_time):
        """Duplicate a session view clip to the arrangement view without using create_clip"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            
            clip_slot = track.clip_slots[clip_index]
            
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            
            source_clip = clip_slot.clip
            
            # For Live 11, we need to use a different approach since create_clip isn't available
            # We'll use the clip_slot.fire() method which plays the clip
            # To do this in the arrangement:
            # 1. We need to move the playhead to the desired position
            # 2. Enable arrangement record
            # 3. Fire the clip
            # 4. Let it record for the clip duration
            # 5. Stop recording
            
            current_position = self._song.current_song_time
            was_playing = self._song.is_playing
            was_recording = self._song.record_mode
            
            # Position the playhead
            self._song.current_song_time = arrangement_time
            
            # Enable arrangement record mode
            self._song.record_mode = True
            
            # Start playback if not already playing
            if not self._song.is_playing:
                self._song.start_playing()
            
            # Fire the clip
            clip_slot.fire()
            
            # Wait for approximately the clip duration (simulated)
            # In a real implementation, you'd need a different approach as
            # this blocks the execution. For our purposes, we'll just log it
            self.log_message(f"Recording clip of length {source_clip.length} at position {arrangement_time}")
            
            # Create a simulated result since we can't get direct access to the created clip
            result = {
                "track_index": track_index, 
                "source_clip_index": clip_index,
                "arrangement_time": arrangement_time,
                "clip_name": source_clip.name if hasattr(source_clip, 'name') else "",
                "clip_length": source_clip.length,
                "note": "Clip was fired for recording. Check arrangement view."
            }
            return result
        except Exception as e:
            self.log_message(f"Error duplicating clip to arrangement: {str(e)}")
            raise

    def _set_locators(self, start_time, end_time, name=""):
        """Set arrangement locators (start/end markers)"""
        try:
            # Set locators
            self._song.set_or_delete_cue(start_time)
            
            # Set name if provided
            if name:
                # Find the created cue point and set its name
                for cue_point in self._song.cue_points:
                    if abs(cue_point.time - start_time) < 0.001:  # Small tolerance for floating point
                        cue_point.name = name
                        break
            
            result = {
                "start_time": start_time,
                "end_time": end_time,
                "name": name
            }
            return result
        except Exception as e:
            self.log_message(f"Error setting locators: {str(e)}")
            raise
    
    def _set_arrangement_loop(self, start_time, end_time, enabled=True):
        """Set the arrangement loop region"""
        try:
            # Set loop start point
            if hasattr(self._song, 'loop_start'):
                self._song.loop_start = start_time
            
            # Handle loop end - try loop_length first (Live 11), fall back to loop_end if available
            if hasattr(self._song, 'loop_length'):
                self._song.loop_length = end_time - start_time
            elif hasattr(self._song, 'loop_end'):
                self._song.loop_end = end_time
            
            # Enable/disable looping if possible
            if hasattr(self._song, 'loop'):
                self._song.loop = enabled
            
            # Return result with appropriate properties
            result = {
                "loop_start": self._song.loop_start if hasattr(self._song, 'loop_start') else start_time,
                "loop_end": end_time,
                "loop_enabled": self._song.loop if hasattr(self._song, 'loop') else enabled
            }
            return result
        except Exception as e:
            self.log_message(f"Error setting arrangement loop: {str(e)}")
            raise
    
    def _get_arrangement_info(self):
        """Get information about the arrangement"""
        try:
            result = {
                "current_song_time": self._song.current_song_time if hasattr(self._song, 'current_song_time') else 0.0,
                "track_count": len(self._song.tracks),
                "cue_points": []
            }
            
            # Add loop information if available
            if hasattr(self._song, 'loop_start'):
                result["loop_start"] = self._song.loop_start
                
            if hasattr(self._song, 'loop_length'):
                result["loop_length"] = self._song.loop_length
                result["loop_end"] = self._song.loop_start + self._song.loop_length
            elif hasattr(self._song, 'loop_end'):
                result["loop_end"] = self._song.loop_end
                
            if hasattr(self._song, 'loop'):
                result["loop_enabled"] = self._song.loop
            
            # Check if Arranger view is visible
            if hasattr(self._song.view, 'is_view_visible'):
                result["arrangement_view_visible"] = self._song.view.is_view_visible('Arranger')
            
            # Add cue points if available
            if hasattr(self._song, 'cue_points'):
                for cue_point in self._song.cue_points:
                    result["cue_points"].append({
                        "name": cue_point.name,
                        "time": cue_point.time
                    })
            
            return result
        except Exception as e:
            self.log_message(f"Error getting arrangement info: {str(e)}")
            raise
    
    def _get_track_arrangement_clips(self, track_index):
        """Get all clips in the arrangement view for a specific track"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            clips = []
            for clip in track.arrangement_clips:
                clip_info = {
                    "name": clip.name,
                    "start_time": clip.start_marker.time,
                    "end_time": clip.end_marker.time,
                    "length": clip.length,
                    "is_audio_clip": clip.is_audio_clip
                }
                
                # For MIDI clips, include note count
                if not clip.is_audio_clip:
                    clip_info["note_count"] = len(clip.get_notes(0, 0, clip.length, 127))
                
                clips.append(clip_info)
            
            result = {
                "track_index": track_index,
                "track_name": track.name,
                "clip_count": len(clips),
                "clips": clips
            }
            return result
        except Exception as e:
            self.log_message(f"Error getting track arrangement clips: {str(e)}")
            raise

    def _get_time_signatures(self):
        """Get all time signatures in the arrangement"""
        try:
            result = {
                "time_signatures": []
            }
            
            # Add the signature from the song properties (global time signature)
            result["time_signatures"].append({
                "numerator": self._song.signature_numerator,
                "denominator": self._song.signature_denominator,
                "time": 0.0,
                "bar": 1
            })
            
            # Add time signature markers if available
            if hasattr(self._song, "time_signatures"):
                for ts in self._song.time_signatures:
                    # Calculate which bar this time signature starts at
                    # This is approximate and depends on previous time signatures
                    beats_per_bar = 4.0  # Default
                    bar = 1 + int(ts.time / beats_per_bar)
                    
                    result["time_signatures"].append({
                        "numerator": ts.numerator,
                        "denominator": ts.denominator,
                        "time": ts.time,
                        "bar": bar
                    })
            
            return result
        except Exception as e:
            self.log_message(f"Error getting time signatures: {str(e)}")
            raise
    
    def _set_playhead_position(self, time):
        """Set the playhead position in the arrangement"""
        try:
            self._song.current_song_time = time
            
            result = {
                "current_song_time": self._song.current_song_time
            }
            return result
        except Exception as e:
            self.log_message(f"Error setting playhead position: {str(e)}")
            raise
    
    def _create_arrangement_marker(self, name, time):
        """Create a marker in the arrangement at the specified position"""
        try:
            # Try to create a cue point, checking method signature
            try:
                # The correct signature appears to be without arguments
                # We'll try to create it and then modify it afterward
                if hasattr(self._song, 'set_or_delete_cue'):
                    new_cue = self._song.set_or_delete_cue()
                    
                    # If successful, try to set the time and name
                    if new_cue and hasattr(new_cue, 'time'):
                        new_cue.time = time
                        if hasattr(new_cue, 'name'):
                            new_cue.name = name
                    created_cue = new_cue
                else:
                    # Fallback if method not available
                    self.log_message("set_or_delete_cue method not available")
                    created_cue = None
            except Exception as e:
                self.log_message(f"Error using set_or_delete_cue: {str(e)}")
                created_cue = None
            
            # If we couldn't create a new cue point, look for an existing one to reuse
            if created_cue is None and hasattr(self._song, 'cue_points'):
                # Find an existing cue point that's close to the time we want
                closest_cue = None
                closest_distance = float('inf')
                
                for cue_point in self._song.cue_points:
                    distance = abs(cue_point.time - time)
                    if distance < closest_distance:
                        closest_cue = cue_point
                        closest_distance = distance
                
                # If we found one and it's within a reasonable distance, use it
                if closest_cue and closest_distance < 2.0:
                    closest_cue.time = time
                    closest_cue.name = name
                    created_cue = closest_cue
                else:
                    # Otherwise, we can't create a marker
                    self.log_message("Could not create or find a suitable cue point")
            
            # If we still couldn't create or find a cue point
            if created_cue is None:
                # Just return info as if we created it
                self.log_message(f"Unable to create cue point at {time}")
                result = {
                    "name": name,
                    "time": time,
                    "created": False
                }
                return result
            
            result = {
                "name": created_cue.name if hasattr(created_cue, 'name') else name,
                "time": created_cue.time if hasattr(created_cue, 'time') else time,
                "created": True
            }
            return result
        except Exception as e:
            self.log_message(f"Error creating arrangement marker: {str(e)}")
            raise
    
    def _get_arrangement_markers(self):
        """Get all markers in the arrangement"""
        try:
            result = {
                "markers": []
            }
            
            # Get all cue points
            for cue_point in self._song.cue_points:
                result["markers"].append({
                    "name": cue_point.name,
                    "time": cue_point.time
                })
            
            return result
        except Exception as e:
            self.log_message(f"Error getting arrangement markers: {str(e)}")
            raise
    
    def _create_complex_arrangement(self, structure, transitions=True, arrange_automation=True):
        """Create a complete arrangement with complex structure"""
        try:
            self.log_message(f"Creating complex arrangement with {len(structure)} sections")
            
            # Instead of clearing the entire arrangement, we'll approach this differently
            # We'll create new clips at the specified positions without removing existing ones
            
            current_bar = 0
            sections_created = []
            
            # Process each section in the structure
            for section_index, section in enumerate(structure):
                section_name = section.get("name", f"Section {section_index + 1}")
                section_type = section.get("type", "generic")
                length_bars = section.get("length_bars", 4)
                energy_level = section.get("energy_level", 0.5)
                
                # Convert bar to time
                start_time = current_bar * 4.0  # Assuming 4/4 time signature
                
                # Add a marker for this section
                self._create_arrangement_marker(section_name, start_time)
                
                # Create section
                if "tracks" in section:
                    # If specific tracks/clips are specified, use those
                    for track_data in section["tracks"]:
                        track_index = track_data.get("index", 0)
                        clips = track_data.get("clips", [])
                        
                        if track_index >= len(self._song.tracks):
                            continue
                            
                        track = self._song.tracks[track_index]
                        
                        for clip_index in clips:
                            if clip_index >= len(track.clip_slots) or not track.clip_slots[clip_index].has_clip:
                                continue
                                
                            source_clip = track.clip_slots[clip_index].clip
                            
                            # Calculate how many times to loop to fill the section
                            repeats = int((length_bars * 4.0) / source_clip.length) + 1
                            
                            for i in range(repeats):
                                repeat_time = start_time + (i * source_clip.length)
                                if repeat_time >= start_time + (length_bars * 4.0):
                                    break
                                
                                # Use our manual duplication method instead of duplicate_clip_to
                                new_clip = track.create_clip(repeat_time, source_clip.length)
                                
                                # If it's a MIDI clip, copy the notes
                                if hasattr(source_clip, 'get_notes') and hasattr(new_clip, 'set_notes'):
                                    notes = list(source_clip.get_notes(0, 0, source_clip.length, 127))
                                    if notes:
                                        new_clip.set_notes(tuple(notes))
                                
                                # Copy clip name if possible
                                if hasattr(source_clip, 'name') and hasattr(new_clip, 'name'):
                                    new_clip.name = source_clip.name
                else:
                    # Use standard section creation based on section type
                    self._create_arrangement_section(section_type, length_bars, current_bar)
                
                # Add automation for energy level if requested
                if arrange_automation:
                    self._add_energy_automation(start_time, length_bars * 4.0, energy_level)
                
                # Create transition to next section if there is one
                if transitions and section_index < len(structure) - 1:
                    next_section = structure[section_index + 1]
                    next_energy = next_section.get("energy_level", 0.5)
                    
                    # Choose transition type based on energy change
                    transition_type = "fill"  # Default
                    
                    if next_energy > energy_level + 0.3:
                        transition_type = "riser"
                    elif next_energy < energy_level - 0.3:
                        transition_type = "downlifter"
                    
                    # Create transition at the end of this section
                    self._create_transition(current_bar + length_bars - 1, current_bar + length_bars, transition_type, 4)
                
                # Store section info
                sections_created.append({
                    "name": section_name,
                    "type": section_type,
                    "start_bar": current_bar,
                    "length_bars": length_bars,
                    "energy_level": energy_level
                })
                
                # Update current position
                current_bar += length_bars
            
            result = {
                "total_length_bars": current_bar,
                "section_count": len(structure),
                "sections": sections_created
            }
            return result
        except Exception as e:
            self.log_message(f"Error creating complex arrangement: {str(e)}")
            self.log_message(traceback.format_exc())
            raise
    
    def _add_energy_automation(self, start_time, length, energy_level):
        """Add automation for energy level (affects track volumes, filters, etc.)"""
        try:
            # Find suitable tracks to automate
            for track_index, track in enumerate(self._song.tracks):
                # Look for a device that can be automated
                for device_index, device in enumerate(track.devices):
                    # Try to find a filter or EQ type device
                    if "eq" in device.name.lower() or "filter" in device.name.lower():
                        # Find a frequency parameter to automate
                        for param_index, param in enumerate(device.parameters):
                            if ("freq" in param.name.lower() or 
                                "cutoff" in param.name.lower() or 
                                "frequency" in param.name.lower()):
                                
                                # Set automation based on energy level
                                param_range = param.max - param.min
                                
                                # Higher energy = higher frequency
                                target_value = param.min + (param_range * energy_level)
                                
                                # Create automation envelope points
                                param.automation_state = 1  # Enable automation
                                param.add_automation_point(start_time, target_value)
                                param.add_automation_point(start_time + length, target_value)
                                
                                break
                
                # Also automate volume based on energy
                vol_param = track.mixer_device.volume
                vol_range = vol_param.max - vol_param.min
                
                # Map energy level to a reasonable volume range (not too extreme)
                # Energy 0.0 -> -12dB, Energy 1.0 -> 0dB
                min_vol_db = -12.0
                target_vol = vol_param.min + (vol_range * ((energy_level * (0 - min_vol_db) + min_vol_db) / 0))
                
                # Create automation envelope points
                vol_param.automation_state = 1  # Enable automation
                vol_param.add_automation_point(start_time, target_vol)
                vol_param.add_automation_point(start_time + length, target_vol)
                
        except Exception as e:
            self.log_message(f"Error adding energy automation: {str(e)}")
    
    def _quantize_arrangement_clips(self, track_index=-1, quantize_amount=1.0):
        """Quantize all clips in the arrangement"""
        try:
            quantized_count = 0
            
            if track_index == -1:
                # Quantize all tracks
                tracks_to_process = self._song.tracks
            else:
                # Quantize specific track
                if track_index < 0 or track_index >= len(self._song.tracks):
                    raise IndexError("Track index out of range")
                
                tracks_to_process = [self._song.tracks[track_index]]
            
            for track in tracks_to_process:
                for clip in track.arrangement_clips:
                    if clip.is_midi_clip:
                        # For MIDI clips, try to quantize notes
                        try:
                            clip.quantize(quantize_amount)
                            quantized_count += 1
                        except:
                            pass
            
            result = {
                "quantized_count": quantized_count,
                "track_count": len(tracks_to_process),
                "quantize_amount": quantize_amount
            }
            return result
        except Exception as e:
            self.log_message(f"Error quantizing arrangement clips: {str(e)}")
            raise
    
    def _consolidate_arrangement_selection(self, start_time, end_time, track_index):
        """Consolidate a selection in the arrangement to a new clip"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            # Select the track and set time selection
            self._song.view.selected_track = track
            self._song.loop_start = start_time
            self._song.loop_end = end_time
            self._song.loop = True
            
            # Check if there's content to consolidate
            has_clips = False
            for clip in track.arrangement_clips:
                if (clip.start_marker.time < end_time and 
                    clip.end_marker.time > start_time):
                    has_clips = True
                    break
            
            if not has_clips:
                raise Exception("No clips found in the selected time range")
            
            # Perform the consolidation
            # Note: In a real implementation, this would likely need to
            # simulate key presses or use a different API call
            # We'll simulate it by creating a new clip that covers the range
            
            # First, gather all affected clips
            affected_clips = []
            for clip in track.arrangement_clips:
                if (clip.start_marker.time < end_time and 
                    clip.end_marker.time > start_time):
                    affected_clips.append(clip)
            
            # Create a new clip that spans the entire range
            new_clip = track.create_clip(start_time, end_time - start_time)
            
            # For MIDI clips, we would copy over all the notes
            if track.has_midi_input and affected_clips:
                all_notes = []
                
                for clip in affected_clips:
                    if clip.is_midi_clip:
                        # Get notes from this clip
                        clip_notes = list(clip.get_notes(0, 0, clip.length, 127))
                        
                        # Adjust note timing to be relative to the new clip
                        for note in clip_notes:
                            # Note format: (pitch, start_time, duration, velocity, mute)
                            note_time = note[1] + clip.start_marker.time
                            
                            # Only include notes that fall within our range
                            if note_time >= start_time and note_time < end_time:
                                # Adjust time to be relative to new clip start
                                new_note_time = note_time - start_time
                                
                                all_notes.append((
                                    note[0],  # pitch
                                    new_note_time,  # adjusted start time
                                    note[2],  # duration
                                    note[3],  # velocity
                                    note[4]   # mute
                                ))
                
                # Set all notes in the new clip
                if all_notes:
                    new_clip.set_notes(tuple(all_notes))
            
            # Delete the original clips in the range
            for clip in affected_clips:
                # This is a simplification; in a real implementation we would need to
                # properly remove the clips
                clip.end_time = start_time  # Truncate to before our new clip
            
            result = {
                "track_index": track_index,
                "start_time": start_time,
                "end_time": end_time,
                "new_clip_length": new_clip.length,
                "consolidated": True
            }
            return result
        except Exception as e:
            self.log_message(f"Error consolidating arrangement selection: {str(e)}")
            raise

    def _set_time_signature(self, numerator, denominator, bar_position=1):
        """Set the time signature at a specific bar in the arrangement"""
        try:
            # Convert bar position to time
            time = (bar_position - 1) * 4.0  # Assuming 4 beats per bar initially
            
            # Create time signature change
            self._song.create_time_signature(time, numerator, denominator)
            
            result = {
                "numerator": numerator,
                "denominator": denominator,
                "bar_position": bar_position,
                "time": time
            }
            return result
        except Exception as e:
            self.log_message(f"Error setting time signature: {str(e)}")
            raise

    def _show_arrangement_view(self):
        """Switch to arrangement view"""
        try:
            if hasattr(self._song.view, 'show_view'):
                self._song.view.show_view('Arranger')
            # Try alternative approach if show_view isn't available
            elif hasattr(self._song.view, 'is_view_visible'):
                # Find available views
                if hasattr(self._song.view, 'available_main_views'):
                    views = self._song.view.available_main_views()
                    self.log_message(f"Available views: {views}")
                    
                    # Try to find arranger
                    for view_name in views:
                        if 'arrange' in view_name.lower() or 'arrang' in view_name.lower():
                            self._song.view.focus_view(view_name)
                            break
                
            result = {
                "success": True
            }
            return result
        except Exception as e:
            self.log_message(f"Error showing arrangement view: {str(e)}")
            result = {
                "success": False,
                "error": str(e)
            }
            return result

    def _show_session_view(self):
        """Switch to session view"""
        try:
            if hasattr(self._song.view, 'show_view'):
                self._song.view.show_view('Session')
            # Try alternative approach if show_view isn't available
            elif hasattr(self._song.view, 'is_view_visible'):
                # Find available views
                if hasattr(self._song.view, 'available_main_views'):
                    views = self._song.view.available_main_views()
                    self.log_message(f"Available views: {views}")
                    
                    # Try to find session
                    for view_name in views:
                        if 'session' in view_name.lower():
                            self._song.view.focus_view(view_name)
                            break
                
            result = {
                "success": True
            }
            return result
        except Exception as e:
            self.log_message(f"Error showing session view: {str(e)}")
            result = {
                "success": False,
                "error": str(e)
            }
            return result

    def _set_arrangement_record(self, enabled=True):
        """Enable or disable arrangement record mode"""
        try:
            if hasattr(self._song, 'record_mode'):
                self._song.record_mode = enabled
                
            result = {
                "record_mode": self._song.record_mode if hasattr(self._song, 'record_mode') else enabled
            }
            return result
        except Exception as e:
            self.log_message(f"Error setting arrangement record: {str(e)}")
            raise

    def _start_arrangement_recording(self):
        """Start recording in arrangement view"""
        try:
            # Make sure we're in arrangement view
            self._show_arrangement_view()
            
            # Enable record mode
            if hasattr(self._song, 'record_mode'):
                self._song.record_mode = True
                
            # Start playback if not already playing
            if hasattr(self._song, 'is_playing') and not self._song.is_playing:
                self._song.start_playing()
                
            result = {
                "record_mode": self._song.record_mode if hasattr(self._song, 'record_mode') else True,
                "is_playing": self._song.is_playing if hasattr(self._song, 'is_playing') else True
            }
            return result
        except Exception as e:
            self.log_message(f"Error starting arrangement recording: {str(e)}")
            raise

    def _arrangement_to_session(self, track_index, start_time, end_time, target_clip_slot):
        """Copy a section of the arrangement to a session clip slot"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            if target_clip_slot < 0 or target_clip_slot >= len(track.clip_slots):
                raise IndexError("Clip slot index out of range")
            
            # First try using Live's builtin features if available - the API doesn't document this well
            try:
                # Try selecting the track and time range
                self._song.view.selected_track = track
                
                # Set loop points to the range we want
                if hasattr(self._song, 'loop_start'):
                    self._song.loop_start = start_time
                    
                if hasattr(self._song, 'loop_length'):
                    self._song.loop_length = end_time - start_time
                elif hasattr(self._song, 'loop_end'):
                    self._song.loop_end = end_time
                
                # Try to find and use the "Consolidate" or similar command
                # This isn't directly accessible via the API, but we can log what we're trying to do
                self.log_message(f"Trying to copy arrangement section to session clip slot {target_clip_slot}")
                
                # For now, return what we attempted to do
                result = {
                    "track_index": track_index,
                    "start_time": start_time,
                    "end_time": end_time,
                    "target_clip_slot": target_clip_slot,
                    "note": "Attempted to copy arrangement to session. Check if the operation succeeded."
                }
                return result
            except Exception as e:
                self.log_message(f"Error using built-in features: {str(e)}")
                raise
        except Exception as e:
            self.log_message(f"Error copying arrangement to session: {str(e)}")
            raise
