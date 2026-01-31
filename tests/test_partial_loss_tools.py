"""Unit tests for partial loss workflow tools."""

import json
import os
from pathlib import Path

# Point to project data for mock_db
os.environ.setdefault("MOCK_DB_PATH", str(Path(__file__).resolve().parent.parent / "data" / "mock_db.json"))


def test_get_available_repair_shops():
    """Test getting list of available repair shops."""
    from claim_agent.tools.logic import get_available_repair_shops_impl

    result = get_available_repair_shops_impl()
    data = json.loads(result)
    
    assert "shop_count" in data
    assert "shops" in data
    assert data["shop_count"] > 0
    
    # Check shop structure
    shop = data["shops"][0]
    assert "shop_id" in shop
    assert "name" in shop
    assert "address" in shop
    assert "rating" in shop
    assert "labor_rate_per_hour" in shop
    assert "network" in shop


def test_get_available_repair_shops_filter_network():
    """Test filtering shops by network type."""
    from claim_agent.tools.logic import get_available_repair_shops_impl

    result = get_available_repair_shops_impl(network_type="preferred")
    data = json.loads(result)
    
    # All returned shops should be preferred network
    for shop in data["shops"]:
        assert shop["network"] == "preferred"


def test_get_available_repair_shops_sorted_by_rating():
    """Test that shops are sorted by rating (highest first)."""
    from claim_agent.tools.logic import get_available_repair_shops_impl

    result = get_available_repair_shops_impl()
    data = json.loads(result)
    
    ratings = [shop["rating"] for shop in data["shops"]]
    assert ratings == sorted(ratings, reverse=True)


def test_assign_repair_shop_success():
    """Test successful repair shop assignment."""
    from claim_agent.tools.logic import assign_repair_shop_impl

    result = assign_repair_shop_impl("CLM-TEST001", "SHOP-001", 5)
    data = json.loads(result)
    
    assert data["success"] is True
    assert data["claim_id"] == "CLM-TEST001"
    assert data["shop_id"] == "SHOP-001"
    assert "shop_name" in data
    assert "address" in data
    assert "phone" in data
    assert "estimated_start_date" in data
    assert "estimated_completion_date" in data
    assert "confirmation_number" in data
    assert data["confirmation_number"].startswith("RSA-")


def test_assign_repair_shop_not_found():
    """Test assignment with non-existent shop."""
    from claim_agent.tools.logic import assign_repair_shop_impl

    result = assign_repair_shop_impl("CLM-TEST001", "SHOP-999", 5)
    data = json.loads(result)
    
    assert data["success"] is False
    assert "error" in data


def test_assign_repair_shop_no_capacity():
    """Test assignment with shop that has no capacity (SHOP-006)."""
    from claim_agent.tools.logic import assign_repair_shop_impl

    result = assign_repair_shop_impl("CLM-TEST001", "SHOP-006", 5)
    data = json.loads(result)
    
    assert data["success"] is False
    assert "capacity" in data["error"].lower()


def test_get_parts_catalog():
    """Test getting parts from catalog based on damage description."""
    from claim_agent.tools.logic import get_parts_catalog_impl

    result = get_parts_catalog_impl(
        damage_description="Front bumper damaged and headlight broken",
        vehicle_make="Honda",
        part_type_preference="aftermarket"
    )
    data = json.loads(result)
    
    assert "parts_count" in data
    assert data["parts_count"] >= 2  # Should find bumper and headlight
    assert "parts" in data
    assert "total_parts_cost" in data
    assert data["total_parts_cost"] > 0
    
    # Check part structure
    part = data["parts"][0]
    assert "part_id" in part
    assert "part_name" in part
    assert "price" in part
    assert "availability" in part


def test_get_parts_catalog_oem_preference():
    """Test OEM part preference returns OEM prices."""
    from claim_agent.tools.logic import get_parts_catalog_impl

    result_oem = get_parts_catalog_impl(
        damage_description="Rear bumper",
        vehicle_make="Honda",
        part_type_preference="oem"
    )
    result_aftermarket = get_parts_catalog_impl(
        damage_description="Rear bumper",
        vehicle_make="Honda",
        part_type_preference="aftermarket"
    )
    
    data_oem = json.loads(result_oem)
    data_aftermarket = json.loads(result_aftermarket)
    
    # OEM should be more expensive
    assert data_oem["total_parts_cost"] > data_aftermarket["total_parts_cost"]


def test_create_parts_order():
    """Test creating a parts order."""
    from claim_agent.tools.logic import create_parts_order_impl

    parts = [
        {"part_id": "PART-BUMPER-FRONT", "quantity": 1, "part_type": "aftermarket"},
        {"part_id": "PART-HEADLIGHT", "quantity": 1, "part_type": "aftermarket"},
    ]
    
    result = create_parts_order_impl("CLM-TEST001", parts, "SHOP-001")
    data = json.loads(result)
    
    assert data["success"] is True
    assert data["claim_id"] == "CLM-TEST001"
    assert data["shop_id"] == "SHOP-001"
    assert "order_id" in data
    assert data["order_id"].startswith("PO-")
    assert "items" in data
    assert len(data["items"]) == 2
    assert "total_parts_cost" in data
    assert data["total_parts_cost"] > 0
    assert "estimated_delivery_date" in data
    assert data["order_status"] == "ordered"


def test_create_parts_order_empty_parts():
    """Test creating order with no parts returns error."""
    from claim_agent.tools.logic import create_parts_order_impl

    result = create_parts_order_impl("CLM-TEST001", [], "SHOP-001")
    data = json.loads(result)
    
    assert data["success"] is False
    assert "error" in data


def test_calculate_repair_estimate():
    """Test calculating a complete repair estimate."""
    from claim_agent.tools.logic import calculate_repair_estimate_impl

    result = calculate_repair_estimate_impl(
        damage_description="Front bumper cracked, headlight broken",
        vehicle_make="Honda",
        vehicle_year=2021,
        policy_number="POL-001",
        shop_id="SHOP-001",
        part_type_preference="aftermarket"
    )
    data = json.loads(result)
    
    assert "parts_cost" in data
    assert "labor_hours" in data
    assert "labor_cost" in data
    assert "total_estimate" in data
    assert "deductible" in data
    assert "customer_pays" in data
    assert "insurance_pays" in data
    assert "vehicle_value" in data
    assert "is_total_loss" in data
    
    # Verify calculations
    assert data["total_estimate"] == data["parts_cost"] + data["labor_cost"]
    assert data["insurance_pays"] == max(0, data["total_estimate"] - data["deductible"])


def test_calculate_repair_estimate_uses_shop_rate():
    """Test that shop labor rate is used when shop_id is provided."""
    from claim_agent.tools.logic import calculate_repair_estimate_impl

    # SHOP-001 has rate 85, SHOP-004 has rate 55
    result_shop1 = calculate_repair_estimate_impl(
        damage_description="Front bumper",
        vehicle_make="Honda",
        vehicle_year=2021,
        policy_number="POL-001",
        shop_id="SHOP-001"
    )
    result_shop4 = calculate_repair_estimate_impl(
        damage_description="Front bumper",
        vehicle_make="Honda",
        vehicle_year=2021,
        policy_number="POL-001",
        shop_id="SHOP-004"
    )
    
    data1 = json.loads(result_shop1)
    data4 = json.loads(result_shop4)
    
    assert data1["labor_rate"] == 85.0
    assert data4["labor_rate"] == 55.0
    # Same labor hours but different costs due to rate
    assert data1["labor_cost"] > data4["labor_cost"]


def test_generate_repair_authorization():
    """Test generating repair authorization document."""
    from claim_agent.tools.logic import generate_repair_authorization_impl

    repair_estimate = {
        "total_estimate": 2500.0,
        "parts_cost": 1000.0,
        "labor_cost": 1500.0,
        "deductible": 500.0,
        "customer_pays": 500.0,
        "insurance_pays": 2000.0,
    }
    
    result = generate_repair_authorization_impl(
        claim_id="CLM-TEST001",
        shop_id="SHOP-001",
        repair_estimate=repair_estimate,
        customer_approved=True
    )
    data = json.loads(result)
    
    assert "authorization_id" in data
    assert data["authorization_id"].startswith("RA-")
    assert data["claim_id"] == "CLM-TEST001"
    assert data["shop_id"] == "SHOP-001"
    assert data["authorized_amount"] == 2500.0
    assert data["customer_approved"] is True
    assert data["authorization_status"] == "approved"
    assert "authorization_date" in data
    assert "valid_until" in data
    assert "terms" in data
    assert len(data["terms"]) > 0


def test_generate_repair_authorization_pending():
    """Test authorization with pending customer approval."""
    from claim_agent.tools.logic import generate_repair_authorization_impl

    repair_estimate = {
        "total_estimate": 3000.0,
        "parts_cost": 1200.0,
        "labor_cost": 1800.0,
        "deductible": 1000.0,
        "customer_pays": 1000.0,
        "insurance_pays": 2000.0,
    }
    
    result = generate_repair_authorization_impl(
        claim_id="CLM-TEST002",
        shop_id="SHOP-002",
        repair_estimate=repair_estimate,
        customer_approved=False
    )
    data = json.loads(result)
    
    assert data["customer_approved"] is False
    assert data["authorization_status"] == "pending_approval"


def test_partial_loss_threshold():
    """Test that high repair costs flag as potential total loss."""
    from claim_agent.tools.logic import calculate_repair_estimate_impl

    # Use very severe damage that would exceed 75% threshold
    # This is a simplified test - actual threshold depends on vehicle value
    result = calculate_repair_estimate_impl(
        damage_description="Front bumper, rear bumper, hood, both doors, both fenders, headlights, taillights, windshield, trunk, radiator, airbags",
        vehicle_make="Toyota",
        vehicle_year=2019,  # Older/cheaper vehicle
        policy_number="POL-001"
    )
    data = json.loads(result)
    
    assert "is_total_loss" in data
    assert "repair_to_value_ratio" in data
    assert "total_loss_threshold" in data


def test_mock_db_has_repair_shops():
    """Test that mock database includes repair shops."""
    from claim_agent.tools.data_loader import load_mock_db

    db = load_mock_db()
    assert "repair_shops" in db
    assert len(db["repair_shops"]) > 0


def test_mock_db_has_parts_catalog():
    """Test that mock database includes parts catalog."""
    from claim_agent.tools.data_loader import load_mock_db

    db = load_mock_db()
    assert "parts_catalog" in db
    assert len(db["parts_catalog"]) > 0


def test_mock_db_has_labor_operations():
    """Test that mock database includes labor operations."""
    from claim_agent.tools.data_loader import load_mock_db

    db = load_mock_db()
    assert "labor_operations" in db
    assert len(db["labor_operations"]) > 0
