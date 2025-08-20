import React, { useState, useEffect } from 'react';
import './App.css';

function App() {
  const [activeView, setActiveView] = useState('mealCounts'); // 'mealCounts' or 'editMenu'
  const [weekday, setWeekday] = useState('Monday');
  const [menu, setMenu] = useState({
    breakfast: '',
    lunch: '',
    snacks: '',
    dinner: '',
  });
  const [message, setMessage] = useState('');
  const [mealCounts, setMealCounts] = useState(null);

  const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

  useEffect(() => {
    if (activeView === 'mealCounts') {
      fetchMealCounts();
    } else if (activeView === 'editMenu') {
      fetchMenuForWeekday(weekday);
    }
  }, [activeView, weekday]); // Re-fetch when view changes or weekday changes

  const fetchMealCounts = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/mealcount/tomorrow`);
      if (!response.ok) {
        const errorText = await response.text(); // Read response as text for debugging
        throw new Error(`HTTP error! status: ${response.status}, body: ${errorText}`);
      }
      // Check if response is JSON
      const contentType = response.headers.get('content-type');
      if (contentType && contentType.includes('application/json')) {
        const data = await response.json();
        console.log('Received meal counts data:', data); // Log the received data
        if (data) { // Check if data is not null or undefined
          setMealCounts(data);
        } else {
          setMessage('Received empty or invalid data for meal counts.');
        }
      } else {
        const errorText = await response.text(); // Log non-JSON response
        console.error('Non-JSON response for meal counts:', errorText);
        throw new TypeError('Received non-JSON response from meal counts API.');
      }
    } catch (error) {
      console.error('Error fetching meal counts:', error);
      setMessage(`Error fetching meal counts: ${error.message || error.toString()}`);
    }
  };

  const fetchMenuForWeekday = async (selectedWeekday) => {
    try {
      const response = await fetch(`${API_BASE_URL}/menu/${selectedWeekday}`);
      if (response.ok) {
        const data = await response.json();
        setMenu({
          breakfast: data.breakfast || '',
          lunch: data.lunch || '',
          snacks: data.snacks || '',
          dinner: data.dinner || '',
        });
        setMessage(''); // Clear message on successful fetch
      } else if (response.status === 404) {
        setMenu({
          breakfast: '',
          lunch: '',
          snacks: '',
          dinner: '',
        });
        setMessage(`No menu found for ${selectedWeekday}. You can create one.`);
      } else {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
    } catch (error) {
      console.error('Error fetching menu:', error);
      // Check if the error is an HTTP error and not a 404
      if (error.response && error.response.status && error.response.status !== 404) {
          setMessage('Error fetching menu.');
      } else if (!error.response) { // Catch network errors or other non-HTTP errors
          setMessage('Error fetching menu: Network or server issue.');
      }
      // If it's a 404, the message is already set by the else if (response.status === 404) block
    }
  };

  const handleMenuChange = (e) => {
    const { name, value } = e.target;
    setMenu((prevMenu) => ({
      ...prevMenu,
      [name]: value,
    }));
  };

  const handleSubmitMenu = async (e) => {
    e.preventDefault();
    setMessage('');
    try {
      const response = await fetch(`${API_BASE_URL}/menu`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ ...menu, weekday }),
      });
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      const data = await response.json();
      setMessage(data.message);
      // After saving, re-fetch the menu to ensure consistency
      fetchMenuForWeekday(weekday); 
    } catch (error) {
      console.error('Error submitting menu:', error);
      setMessage('Error submitting menu.');
    }
  };

  return (
    <div className="App">
      <div className="dashboard-container">
        <h1>Admin Dashboard</h1>
        <div className="button-container">
          <button onClick={() => { setActiveView('mealCounts'); fetchMealCounts(); }}>Refresh Meal Counts</button>
          <button onClick={() => setActiveView('editMenu')} className={activeView === 'editMenu' ? 'active' : ''}>
            Edit Menu
          </button>
        </div>

        {activeView === 'mealCounts' && (
          <section className="meal-counts-section">
            <h2>Tomorrow's Meal Counts ({mealCounts ? mealCounts.date : 'None'})</h2>
            {mealCounts ? (
              <div className="meal-counts-container">
                <div className="meal-type-counts">
                  <h3>Meal Type Counts</h3>
                  <table>
                    <thead>
                      <tr>
                        <th>Type</th>
                        <th>Count</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr>
                        <td>Veg</td>
                        <td>{mealCounts.veg}</td>
                      </tr>
                      <tr>
                        <td>Non-Veg</td>
                        <td>{mealCounts.non_veg}</td>
                      </tr>
                    </tbody>
                  </table>
                  <h4>Veg Students:</h4>
                  <div className="student-names-table">
                    <table>
                      <thead>
                        <tr><th>Name</th></tr>
                      </thead>
                      <tbody>
                        {mealCounts.veg_students.length > 0 ? (
                          mealCounts.veg_students.map((studentName, index) => (
                            <tr key={index}><td>{studentName}</td></tr>
                          ))
                        ) : (
                          <tr><td>None</td></tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                  <h4>Non-Veg Students:</h4>
                  <div className="student-names-table">
                    <table>
                      <thead>
                        <tr><th>Name</th></tr>
                      </thead>
                      <tbody>
                        {mealCounts.non_veg_students.length > 0 ? (
                          mealCounts.non_veg_students.map((studentName, index) => (
                            <tr key={index}><td>{studentName}</td></tr>
                          ))
                        ) : (
                          <tr><td>None</td></tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>

                <div className="caffeine-counts">
                  <h3>Caffeine Choices Counts</h3>
                  <table>
                    <thead>
                      <tr>
                        <th>Type</th>
                        <th>Count</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(mealCounts.caffeine).map(([type, count]) => (
                        <tr key={type}>
                          <td>{type}</td>
                          <td>{count}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {Object.entries(mealCounts.caffeine_students).map(([type, students]) => (
                    <React.Fragment key={type}>
                      <h4>{type} Students:</h4>
                      <div className="student-names-table">
                        <table>
                          <thead>
                            <tr><th>Name</th></tr>
                          </thead>
                          <tbody>
                            {students.length > 0 ? (
                              students.map((studentName, index) => (
                                <tr key={index}><td>{studentName}</td></tr>
                              ))
                            ) : (
                              <tr><td>None</td></tr>
                            )}
                          </tbody>
                        </table>
                      </div>
                    </React.Fragment>
                  ))}
                </div>
              </div>
            ) : (
              <p>No meal counts data available.</p>
            )}
          </section>
        )}

        {activeView === 'editMenu' && (
          <section className="edit-menu-section">
            <h2>Edit Menu</h2>
            <form key={weekday} onSubmit={handleSubmitMenu} className="menu-form">
              <div className="form-group full-width">
                <label htmlFor="weekday-select">Weekday:</label>
                <select id="weekday-select" value={weekday} onChange={(e) => {
                  setWeekday(e.target.value);
                  // fetchMenuForWeekday is already called by useEffect when weekday changes
                }}>
                  {['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'].map(
                    (day) => (
                      <option key={day} value={day}>
                        {day}
                      </option>
                    )
                  )}
                </select>
              </div>
              <div className="form-row">
                <div className="form-group">
                  <label htmlFor="breakfast-input">Breakfast:</label>
                  <input
                    type="text"
                    id="breakfast-input"
                    name="breakfast"
                    value={menu.breakfast}
                    onChange={handleMenuChange}
                  />
                </div>
                <div className="form-group">
                  <label htmlFor="lunch-input">Lunch:</label>
                  <input
                    type="text"
                    id="lunch-input"
                    name="lunch"
                    value={menu.lunch}
                    onChange={handleMenuChange}
                  />
                </div>
                <div className="form-group">
                  <label htmlFor="snacks-input">Snacks:</label>
                  <input
                    type="text"
                    id="snacks-input"
                    name="snacks"
                    value={menu.snacks}
                    onChange={handleMenuChange}
                  />
                </div>
                <div className="form-group">
                  <label htmlFor="dinner-input">Dinner:</label>
                  <input
                    type="text"
                    id="dinner-input"
                    name="dinner"
                    value={menu.dinner}
                    onChange={handleMenuChange}
                  />
                </div>
              </div>
              <button type="submit" className="full-width-button">Save Menu</button>
            </form>
            {message && <p>{message}</p>}
          </section>
        )}
      </div>
    </div>
  );
}

export default App;
