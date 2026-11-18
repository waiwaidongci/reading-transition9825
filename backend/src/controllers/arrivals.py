from ..services import arrival
class ArrivalsController:
    list=staticmethod(arrival.list_runs)
    create=staticmethod(arrival.create_run)
    targets=staticmethod(arrival.list_targets)
    notes=staticmethod(arrival.list_notes)
    create_note=staticmethod(arrival.create_note)
    approve_note=staticmethod(arrival.approve_note)
    @staticmethod
    def get(db,id):
        from ..utils.serialization import row
        return row(arrival.get_run(db,id))
