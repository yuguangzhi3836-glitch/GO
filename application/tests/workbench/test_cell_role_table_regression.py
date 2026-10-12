from go_hotel.workbench.definitions import WORKSPACES


def test_cell_role_table_shape_and_control_only_partition():
    assert len(WORKSPACES) == 14

    control_only_ids = {workspace.cell_id for workspace in WORKSPACES if workspace.control_only}
    normal_builder_ids = {workspace.cell_id for workspace in WORKSPACES if not workspace.control_only}

    assert control_only_ids.isdisjoint(normal_builder_ids)
    assert len(control_only_ids | normal_builder_ids) == 14

    for workspace in WORKSPACES:
        assert isinstance(workspace.owned_paths, tuple)
        assert workspace.owned_paths
