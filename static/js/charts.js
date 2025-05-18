/**
 * Charts.js - Custom charts for Jira Discord Notifier
 * This file handles the creation and update of charts for project statistics
 */

// Initialize chart objects as global variables so they can be updated
let statusChart = null;
let typeChart = null;
let bugTypeChart = null;

/**
 * Update the status distribution chart
 * @param {Object} statusCounts - Object with status names as keys and counts as values
 */
function updateStatusChart(statusCounts) {
    const ctx = document.getElementById('statusChart').getContext('2d');
    
    // Destroy existing chart if it exists
    if (statusChart) {
        statusChart.destroy();
    }
    
    // Generate colors for the status chart
    const colors = generateChartColors(Object.keys(statusCounts).length);
    
    statusChart = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: Object.keys(statusCounts),
            datasets: [{
                data: Object.values(statusCounts),
                backgroundColor: colors,
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            plugins: {
                legend: {
                    position: 'right',
                    labels: {
                        boxWidth: 15,
                        padding: 15
                    }
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const label = context.label || '';
                            const value = context.parsed || 0;
                            const total = context.dataset.data.reduce((a, b) => a + b, 0);
                            const percentage = Math.round((value * 100) / total);
                            return `${label}: ${value} (${percentage}%)`;
                        }
                    }
                }
            }
        }
    });
}

/**
 * Update the issue type distribution chart
 * @param {Object} issueTypes - Object with issue type names as keys and counts as values
 */
function updateTypeChart(issueTypes) {
    const ctx = document.getElementById('typeChart').getContext('2d');
    
    // Destroy existing chart if it exists
    if (typeChart) {
        typeChart.destroy();
    }
    
    // Generate colors for the type chart
    const colors = generateChartColors(Object.keys(issueTypes).length, true);
    
    typeChart = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: Object.keys(issueTypes),
            datasets: [{
                data: Object.values(issueTypes),
                backgroundColor: colors,
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            plugins: {
                legend: {
                    position: 'right',
                    labels: {
                        boxWidth: 15,
                        padding: 15
                    }
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const label = context.label || '';
                            const value = context.parsed || 0;
                            const total = context.dataset.data.reduce((a, b) => a + b, 0);
                            const percentage = Math.round((value * 100) / total);
                            return `${label}: ${value} (${percentage}%)`;
                        }
                    }
                }
            }
        }
    });
}

/**
 * Create a bug status chart showing regular vs reopened bugs
 * @param {number} bugsCount - Total number of bugs
 * @param {number} reopenedBugsCount - Number of reopened bugs
 */
function updateBugStatusChart(bugsCount, reopenedBugsCount) {
    const ctx = document.getElementById('bugStatusChart');
    if (!ctx) {
        console.error("Bug status chart canvas not found");
        return;
    }
    
    const regularBugsCount = bugsCount - reopenedBugsCount;
    
    // Destroy existing chart if it exists
    if (bugTypeChart) {
        bugTypeChart.destroy();
    }
    
    bugTypeChart = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: ['Regular Bugs', 'Reopened Bugs'],
            datasets: [{
                data: [regularBugsCount, reopenedBugsCount],
                backgroundColor: ['#36A2EB', '#FF6384'],
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            plugins: {
                legend: {
                    position: 'right',
                    labels: {
                        boxWidth: 15,
                        padding: 15
                    }
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const label = context.label || '';
                            const value = context.parsed || 0;
                            const total = context.dataset.data.reduce((a, b) => a + b, 0);
                            const percentage = Math.round((value * 100) / total);
                            return `${label}: ${value} (${percentage}%)`;
                        }
                    }
                }
            }
        }
    });
}

/**
 * Generate colors for chart segments
 * @param {number} count - Number of colors needed
 * @param {boolean} usePresetColors - Whether to use a preset color palette
 * @returns {Array} Array of color strings
 */
function generateChartColors(count, usePresetColors = false) {
    // Predefined color palettes
    const statusColors = [
        '#4e73df', // Blue
        '#1cc88a', // Green
        '#36b9cc', // Cyan
        '#f6c23e', // Yellow
        '#e74a3b', // Red
        '#6f42c1', // Purple
        '#fd7e14', // Orange
        '#20c997', // Teal
        '#6c757d', // Gray
        '#17a2b8', // Info
        '#28a745', // Success
        '#dc3545', // Danger
        '#ffc107', // Warning
        '#007bff', // Primary
        '#6610f2', // Indigo
        '#6f42c1'  // Purple
    ];
    
    const typeColors = {
        'Bug': '#e74a3b',       // Red
        'Task': '#4e73df',      // Blue
        'Epic': '#6f42c1',      // Purple
        'Story': '#1cc88a',     // Green
        'Sub-task': '#36b9cc',  // Cyan
        'Improvement': '#f6c23e' // Yellow
    };
    
    const colors = [];
    
    if (usePresetColors) {
        // First try to use type-specific colors for common issue types
        const labels = Object.keys(typeColors);
        for (let i = 0; i < count; i++) {
            const label = labels[i].toLowerCase();
            if (typeColors[label]) {
                colors.push(typeColors[label]);
            } else if (i < statusColors.length) {
                colors.push(statusColors[i]);
            } else {
                // Generate a random color if we run out of predefined ones
                const r = Math.floor(Math.random() * 200) + 55;
                const g = Math.floor(Math.random() * 200) + 55;
                const b = Math.floor(Math.random() * 200) + 55;
                colors.push(`rgba(${r}, ${g}, ${b}, 0.8)`);
            }
        }
    } else {
        // Use status colors for status chart
        for (let i = 0; i < count; i++) {
            if (i < statusColors.length) {
                colors.push(statusColors[i]);
            } else {
                // Generate a random color if we run out of predefined ones
                const r = Math.floor(Math.random() * 200) + 55;
                const g = Math.floor(Math.random() * 200) + 55;
                const b = Math.floor(Math.random() * 200) + 55;
                colors.push(`rgba(${r}, ${g}, ${b}, 0.8)`);
            }
        }
    }
    
    return colors;
}