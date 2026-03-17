function filterScholarships() {
    const filterValue = document.getElementById('dept-filter').value;
    const searchVal = document.getElementById('search-input').value.toLowerCase();
    const cards = document.getElementsByClassName('preview-card');

    for (let card of cards) {
        const title = card.querySelector('h3').innerText.toLowerCase();
        const cardDept = card.getAttribute('data-dept');

        const matchesSearch = title.includes(searchVal);
        const matchesDept = (filterValue === 'all' || cardDept === filterValue);

        if (matchesSearch && matchesDept) {
            card.style.display = 'flex'; 
        } else {
            card.style.display = 'none';
        }
    }
}

function resetDropdown() {
    document.getElementById('dept-filter').value = 'all';
    filterScholarships();
}
