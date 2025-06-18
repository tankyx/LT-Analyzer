'use client';

import { useState, useEffect } from 'react';
import { useAuth } from '../../contexts/AuthContext';
import { API_BASE_URL } from '../../../utils/config';

interface User {
  id: number;
  username: string;
  email: string;
  role: string;
  created_at: string;
  last_login: string;
  is_active: boolean;
}

interface Track {
  id: number;
  name: string;
  location: string;
  length_meters: number;
  description: string;
  timing_url: string;
  websocket_url: string;
  column_mappings: Record<string, unknown> | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

interface AdminPanelProps {
  isDarkMode: boolean;
}

export default function AdminPanel({ isDarkMode }: AdminPanelProps) {
  const { user } = useAuth();
  const [activeSubTab, setActiveSubTab] = useState<'users' | 'tracks'>('users');
  const [users, setUsers] = useState<User[]>([]);
  const [tracks, setTracks] = useState<Track[]>([]);
  const [loading, setLoading] = useState(false); // eslint-disable-line @typescript-eslint/no-unused-vars
  const [showUserModal, setShowUserModal] = useState(false);
  const [showTrackModal, setShowTrackModal] = useState(false);
  const [editingUser, setEditingUser] = useState<User | null>(null);
  const [editingTrack, setEditingTrack] = useState<Track | null>(null);

  const [userForm, setUserForm] = useState({
    username: '',
    password: '',
    email: '',
    role: 'user',
  });

  const [trackForm, setTrackForm] = useState({
    name: '',
    location: '',
    length_meters: '',
    description: '',
    timing_url: '',
    websocket_url: '',
    is_active: true,
  });

  useEffect(() => {
    if (user?.role === 'admin') {
      fetchUsers();
      fetchTracks();
    }
  }, [user]);

  const fetchUsers = async () => {
    setLoading(true);
    try {
      const response = await fetch(`${API_BASE_URL}/api/admin/users`, {
        credentials: 'include',
      });
      if (response.ok) {
        const data = await response.json();
        setUsers(data);
      }
    } catch (error) {
      console.error('Failed to fetch users:', error);
    } finally {
      setLoading(false);
    }
  };

  const fetchTracks = async () => {
    setLoading(true);
    try {
      const response = await fetch(`${API_BASE_URL}/api/admin/tracks`, {
        credentials: 'include',
      });
      if (response.ok) {
        const data = await response.json();
        setTracks(data);
      }
    } catch (error) {
      console.error('Failed to fetch tracks:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleCreateUser = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/admin/users`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
        body: JSON.stringify(userForm),
      });

      if (response.ok) {
        setShowUserModal(false);
        setUserForm({ username: '', password: '', email: '', role: 'user' });
        fetchUsers();
      }
    } catch (error) {
      console.error('Failed to create user:', error);
    }
  };

  const handleUpdateUser = async () => {
    if (!editingUser) return;

    const updates: Record<string, string> = {};
    if (userForm.email !== editingUser.email) updates.email = userForm.email;
    if (userForm.role !== editingUser.role) updates.role = userForm.role;
    if (userForm.password) updates.password = userForm.password;

    try {
      const response = await fetch(`${API_BASE_URL}/api/admin/users/${editingUser.id}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
        body: JSON.stringify(updates),
      });

      if (response.ok) {
        setShowUserModal(false);
        setEditingUser(null);
        setUserForm({ username: '', password: '', email: '', role: 'user' });
        fetchUsers();
      }
    } catch (error) {
      console.error('Failed to update user:', error);
    }
  };

  const handleDeleteUser = async (userId: number) => {
    if (!confirm('Are you sure you want to delete this user?')) return;

    try {
      const response = await fetch(`${API_BASE_URL}/api/admin/users/${userId}`, {
        method: 'DELETE',
        credentials: 'include',
      });

      if (response.ok) {
        fetchUsers();
      }
    } catch (error) {
      console.error('Failed to delete user:', error);
    }
  };

  const handleCreateTrack = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/admin/tracks`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
        body: JSON.stringify({
          ...trackForm,
          length_meters: trackForm.length_meters ? parseInt(trackForm.length_meters) : null,
        }),
      });

      if (response.ok) {
        setShowTrackModal(false);
        setTrackForm({
          name: '',
          location: '',
          length_meters: '',
          description: '',
          timing_url: '',
          websocket_url: '',
          is_active: true,
        });
        fetchTracks();
      }
    } catch (error) {
      console.error('Failed to create track:', error);
    }
  };

  const handleUpdateTrack = async () => {
    if (!editingTrack) return;

    try {
      const response = await fetch(`${API_BASE_URL}/api/admin/tracks/${editingTrack.id}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
        body: JSON.stringify({
          ...trackForm,
          length_meters: trackForm.length_meters ? parseInt(trackForm.length_meters) : null,
        }),
      });

      if (response.ok) {
        setShowTrackModal(false);
        setEditingTrack(null);
        setTrackForm({
          name: '',
          location: '',
          length_meters: '',
          description: '',
          timing_url: '',
          websocket_url: '',
          is_active: true,
        });
        fetchTracks();
      }
    } catch (error) {
      console.error('Failed to update track:', error);
    }
  };

  const handleDeleteTrack = async (trackId: number) => {
    if (!confirm('Are you sure you want to delete this track?')) return;

    try {
      const response = await fetch(`${API_BASE_URL}/api/admin/tracks/${trackId}`, {
        method: 'DELETE',
        credentials: 'include',
      });

      if (response.ok) {
        fetchTracks();
      }
    } catch (error) {
      console.error('Failed to delete track:', error);
    }
  };

  if (!user || user.role !== 'admin') {
    return (
      <div className="p-6 text-center">
        <p className={isDarkMode ? 'text-gray-400' : 'text-gray-600'}>
          Admin access required
        </p>
      </div>
    );
  }

  return (
    <div className="p-6">
      {/* Sub-tabs */}
      <div className={`border-b ${isDarkMode ? 'border-gray-700' : 'border-gray-200'} mb-6`}>
        <nav className="-mb-px flex space-x-8">
          <button
            onClick={() => setActiveSubTab('users')}
            className={`py-2 px-1 border-b-2 font-medium text-sm ${
              activeSubTab === 'users'
                ? 'border-blue-500 text-blue-500'
                : `border-transparent ${isDarkMode ? 'text-gray-400 hover:text-gray-300' : 'text-gray-500 hover:text-gray-700'}`
            }`}
          >
            Users
          </button>
          <button
            onClick={() => setActiveSubTab('tracks')}
            className={`py-2 px-1 border-b-2 font-medium text-sm ${
              activeSubTab === 'tracks'
                ? 'border-blue-500 text-blue-500'
                : `border-transparent ${isDarkMode ? 'text-gray-400 hover:text-gray-300' : 'text-gray-500 hover:text-gray-700'}`
            }`}
          >
            Tracks
          </button>
        </nav>
      </div>

      {/* Users Tab */}
      {activeSubTab === 'users' && (
        <div>
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-xl font-semibold">User Management</h2>
            <button
              onClick={() => {
                setEditingUser(null);
                setUserForm({ username: '', password: '', email: '', role: 'user' });
                setShowUserModal(true);
              }}
              className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
            >
              Add User
            </button>
          </div>

          <div className={`${isDarkMode ? 'bg-gray-800' : 'bg-white'} rounded-lg overflow-hidden shadow`}>
            <table className="min-w-full">
              <thead className={isDarkMode ? 'bg-gray-700' : 'bg-gray-50'}>
                <tr>
                  <th className={`px-6 py-3 text-left text-xs font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-500'} uppercase tracking-wider`}>
                    Username
                  </th>
                  <th className={`px-6 py-3 text-left text-xs font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-500'} uppercase tracking-wider`}>
                    Email
                  </th>
                  <th className={`px-6 py-3 text-left text-xs font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-500'} uppercase tracking-wider`}>
                    Role
                  </th>
                  <th className={`px-6 py-3 text-left text-xs font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-500'} uppercase tracking-wider`}>
                    Status
                  </th>
                  <th className={`px-6 py-3 text-left text-xs font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-500'} uppercase tracking-wider`}>
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className={`divide-y ${isDarkMode ? 'divide-gray-700' : 'divide-gray-200'}`}>
                {users.map((user) => (
                  <tr key={user.id}>
                    <td className="px-6 py-4 whitespace-nowrap">{user.username}</td>
                    <td className="px-6 py-4 whitespace-nowrap">{user.email || '-'}</td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span className={`px-2 inline-flex text-xs leading-5 font-semibold rounded-full ${
                        user.role === 'admin' ? 'bg-purple-100 text-purple-800' : 'bg-green-100 text-green-800'
                      }`}>
                        {user.role}
                      </span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span className={`px-2 inline-flex text-xs leading-5 font-semibold rounded-full ${
                        user.is_active ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'
                      }`}>
                        {user.is_active ? 'Active' : 'Inactive'}
                      </span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm">
                      <button
                        onClick={() => {
                          setEditingUser(user);
                          setUserForm({
                            username: user.username,
                            password: '',
                            email: user.email || '',
                            role: user.role,
                          });
                          setShowUserModal(true);
                        }}
                        className="text-blue-600 hover:text-blue-900 mr-4"
                      >
                        Edit
                      </button>
                      {user.id !== 1 && (
                        <button
                          onClick={() => handleDeleteUser(user.id)}
                          className="text-red-600 hover:text-red-900"
                        >
                          Delete
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Tracks Tab */}
      {activeSubTab === 'tracks' && (
        <div>
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-xl font-semibold">Track Management</h2>
            <button
              onClick={() => {
                setEditingTrack(null);
                setTrackForm({
                  name: '',
                  location: '',
                  length_meters: '',
                  description: '',
                  timing_url: '',
                  websocket_url: '',
                  is_active: true,
                });
                setShowTrackModal(true);
              }}
              className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
            >
              Add Track
            </button>
          </div>

          <div className={`${isDarkMode ? 'bg-gray-800' : 'bg-white'} rounded-lg overflow-hidden shadow`}>
            <table className="min-w-full">
              <thead className={isDarkMode ? 'bg-gray-700' : 'bg-gray-50'}>
                <tr>
                  <th className={`px-6 py-3 text-left text-xs font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-500'} uppercase tracking-wider`}>
                    Name
                  </th>
                  <th className={`px-6 py-3 text-left text-xs font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-500'} uppercase tracking-wider`}>
                    Location
                  </th>
                  <th className={`px-6 py-3 text-left text-xs font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-500'} uppercase tracking-wider`}>
                    Length
                  </th>
                  <th className={`px-6 py-3 text-left text-xs font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-500'} uppercase tracking-wider`}>
                    Status
                  </th>
                  <th className={`px-6 py-3 text-left text-xs font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-500'} uppercase tracking-wider`}>
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className={`divide-y ${isDarkMode ? 'divide-gray-700' : 'divide-gray-200'}`}>
                {tracks.map((track) => (
                  <tr key={track.id}>
                    <td className="px-6 py-4 whitespace-nowrap">{track.name}</td>
                    <td className="px-6 py-4 whitespace-nowrap">{track.location || '-'}</td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      {track.length_meters ? `${track.length_meters}m` : '-'}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span className={`px-2 inline-flex text-xs leading-5 font-semibold rounded-full ${
                        track.is_active ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'
                      }`}>
                        {track.is_active ? 'Active' : 'Inactive'}
                      </span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm">
                      <button
                        onClick={() => {
                          setEditingTrack(track);
                          setTrackForm({
                            name: track.name,
                            location: track.location || '',
                            length_meters: track.length_meters?.toString() || '',
                            description: track.description || '',
                            timing_url: track.timing_url || '',
                            websocket_url: track.websocket_url || '',
                            is_active: track.is_active,
                          });
                          setShowTrackModal(true);
                        }}
                        className="text-blue-600 hover:text-blue-900 mr-4"
                      >
                        Edit
                      </button>
                      <button
                        onClick={() => handleDeleteTrack(track.id)}
                        className="text-red-600 hover:text-red-900"
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* User Modal */}
      {showUserModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
          <div className={`${isDarkMode ? 'bg-gray-800' : 'bg-white'} rounded-lg p-6 max-w-md w-full`}>
            <h3 className="text-lg font-semibold mb-4">
              {editingUser ? 'Edit User' : 'Create User'}
            </h3>
            
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium mb-1">Username</label>
                <input
                  type="text"
                  value={userForm.username}
                  onChange={(e) => setUserForm({ ...userForm, username: e.target.value })}
                  disabled={!!editingUser}
                  className={`w-full px-3 py-2 rounded border ${
                    isDarkMode 
                      ? 'bg-gray-700 border-gray-600 focus:border-blue-500' 
                      : 'bg-white border-gray-300 focus:border-blue-500'
                  } focus:outline-none`}
                />
              </div>
              
              <div>
                <label className="block text-sm font-medium mb-1">
                  {editingUser ? 'New Password (leave blank to keep current)' : 'Password'}
                </label>
                <input
                  type="password"
                  value={userForm.password}
                  onChange={(e) => setUserForm({ ...userForm, password: e.target.value })}
                  className={`w-full px-3 py-2 rounded border ${
                    isDarkMode 
                      ? 'bg-gray-700 border-gray-600 focus:border-blue-500' 
                      : 'bg-white border-gray-300 focus:border-blue-500'
                  } focus:outline-none`}
                  required={!editingUser}
                />
              </div>
              
              <div>
                <label className="block text-sm font-medium mb-1">Email</label>
                <input
                  type="email"
                  value={userForm.email}
                  onChange={(e) => setUserForm({ ...userForm, email: e.target.value })}
                  className={`w-full px-3 py-2 rounded border ${
                    isDarkMode 
                      ? 'bg-gray-700 border-gray-600 focus:border-blue-500' 
                      : 'bg-white border-gray-300 focus:border-blue-500'
                  } focus:outline-none`}
                />
              </div>
              
              <div>
                <label className="block text-sm font-medium mb-1">Role</label>
                <select
                  value={userForm.role}
                  onChange={(e) => setUserForm({ ...userForm, role: e.target.value })}
                  className={`w-full px-3 py-2 rounded border ${
                    isDarkMode 
                      ? 'bg-gray-700 border-gray-600 focus:border-blue-500' 
                      : 'bg-white border-gray-300 focus:border-blue-500'
                  } focus:outline-none`}
                >
                  <option value="user">User</option>
                  <option value="admin">Admin</option>
                </select>
              </div>
            </div>
            
            <div className="flex justify-end space-x-3 mt-6">
              <button
                onClick={() => setShowUserModal(false)}
                className={`px-4 py-2 rounded ${
                  isDarkMode ? 'bg-gray-700 hover:bg-gray-600' : 'bg-gray-200 hover:bg-gray-300'
                }`}
              >
                Cancel
              </button>
              <button
                onClick={editingUser ? handleUpdateUser : handleCreateUser}
                className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
              >
                {editingUser ? 'Update' : 'Create'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Track Modal */}
      {showTrackModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
          <div className={`${isDarkMode ? 'bg-gray-800' : 'bg-white'} rounded-lg p-6 max-w-md w-full max-h-[90vh] overflow-y-auto`}>
            <h3 className="text-lg font-semibold mb-4">
              {editingTrack ? 'Edit Track' : 'Create Track'}
            </h3>
            
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium mb-1">Name</label>
                <input
                  type="text"
                  value={trackForm.name}
                  onChange={(e) => setTrackForm({ ...trackForm, name: e.target.value })}
                  className={`w-full px-3 py-2 rounded border ${
                    isDarkMode 
                      ? 'bg-gray-700 border-gray-600 focus:border-blue-500' 
                      : 'bg-white border-gray-300 focus:border-blue-500'
                  } focus:outline-none`}
                  required
                />
              </div>
              
              <div>
                <label className="block text-sm font-medium mb-1">Location</label>
                <input
                  type="text"
                  value={trackForm.location}
                  onChange={(e) => setTrackForm({ ...trackForm, location: e.target.value })}
                  className={`w-full px-3 py-2 rounded border ${
                    isDarkMode 
                      ? 'bg-gray-700 border-gray-600 focus:border-blue-500' 
                      : 'bg-white border-gray-300 focus:border-blue-500'
                  } focus:outline-none`}
                />
              </div>
              
              <div>
                <label className="block text-sm font-medium mb-1">Length (meters)</label>
                <input
                  type="number"
                  value={trackForm.length_meters}
                  onChange={(e) => setTrackForm({ ...trackForm, length_meters: e.target.value })}
                  className={`w-full px-3 py-2 rounded border ${
                    isDarkMode 
                      ? 'bg-gray-700 border-gray-600 focus:border-blue-500' 
                      : 'bg-white border-gray-300 focus:border-blue-500'
                  } focus:outline-none`}
                />
              </div>
              
              <div>
                <label className="block text-sm font-medium mb-1">Description</label>
                <textarea
                  value={trackForm.description}
                  onChange={(e) => setTrackForm({ ...trackForm, description: e.target.value })}
                  className={`w-full px-3 py-2 rounded border ${
                    isDarkMode 
                      ? 'bg-gray-700 border-gray-600 focus:border-blue-500' 
                      : 'bg-white border-gray-300 focus:border-blue-500'
                  } focus:outline-none`}
                  rows={3}
                />
              </div>
              
              <div>
                <label className="block text-sm font-medium mb-1">Timing URL</label>
                <input
                  type="text"
                  value={trackForm.timing_url}
                  onChange={(e) => setTrackForm({ ...trackForm, timing_url: e.target.value })}
                  className={`w-full px-3 py-2 rounded border ${
                    isDarkMode 
                      ? 'bg-gray-700 border-gray-600 focus:border-blue-500' 
                      : 'bg-white border-gray-300 focus:border-blue-500'
                  } focus:outline-none`}
                />
              </div>
              
              <div>
                <label className="block text-sm font-medium mb-1">WebSocket URL</label>
                <input
                  type="text"
                  value={trackForm.websocket_url}
                  onChange={(e) => setTrackForm({ ...trackForm, websocket_url: e.target.value })}
                  className={`w-full px-3 py-2 rounded border ${
                    isDarkMode 
                      ? 'bg-gray-700 border-gray-600 focus:border-blue-500' 
                      : 'bg-white border-gray-300 focus:border-blue-500'
                  } focus:outline-none`}
                />
              </div>
              
              <div>
                <label className="flex items-center">
                  <input
                    type="checkbox"
                    checked={trackForm.is_active}
                    onChange={(e) => setTrackForm({ ...trackForm, is_active: e.target.checked })}
                    className="mr-2"
                  />
                  <span className="text-sm font-medium">Active</span>
                </label>
              </div>
            </div>
            
            <div className="flex justify-end space-x-3 mt-6">
              <button
                onClick={() => setShowTrackModal(false)}
                className={`px-4 py-2 rounded ${
                  isDarkMode ? 'bg-gray-700 hover:bg-gray-600' : 'bg-gray-200 hover:bg-gray-300'
                }`}
              >
                Cancel
              </button>
              <button
                onClick={editingTrack ? handleUpdateTrack : handleCreateTrack}
                className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
              >
                {editingTrack ? 'Update' : 'Create'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}